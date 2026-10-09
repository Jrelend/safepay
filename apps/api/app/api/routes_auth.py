"""Authentication, sessions and profile endpoints (public API)."""

import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth_context import (
    CurrentUser,
    client_ip,
    csrf_cookie_name,
    session_cookie_name,
)
from app.api.deps import SettingsDep
from app.api.errors import ApiError
from app.core.config import Settings
from app.core.security import WeakPasswordError
from app.db.session import get_db
from app.db.transactions import atomic
from app.models import Admin, User, UserSession
from app.services import accounts
from app.services import rate_limit as rl

router = APIRouter(tags=["auth"])
DbDep = Annotated[Session, Depends(get_db)]
PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")


class Accepted(BaseModel):
    status: Literal["accepted"] = "accepted"


class RegisterIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)
    display_name: str = Field(min_length=2, max_length=100)


class EmailIn(BaseModel):
    email: str = Field(max_length=254)


class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=256)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class ResetConfirmIn(BaseModel):
    token: str = Field(min_length=10, max_length=256)
    new_password: str = Field(max_length=128)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)


class ProfileIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=100)
    phone_e164: str | None = Field(default=None, max_length=16)


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    phone_e164: str | None
    email_verified: bool
    is_admin: bool
    created_at: datetime


class SessionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    user_agent: str
    ip_address: str
    current: bool


def limit(request: Request, limit_: rl.Limit, key: str) -> None:
    try:
        rl.hit(request.app.state.engine, limit_, key)
    except rl.RateLimitedError as exc:
        raise ApiError(429, "rate_limited", "too many attempts, try again later") from exc


def _set_auth_cookies(
    response: Response, settings: Settings, issued: accounts.IssuedSession
) -> None:
    max_age = settings.session_ttl_hours * 3600
    common = {"secure": settings.secure_cookies, "samesite": "lax", "path": "/", "max_age": max_age}
    response.set_cookie(session_cookie_name(settings), issued.token, httponly=True, **common)  # type: ignore[arg-type]
    # Readable by the web app's JS so it can echo it in X-CSRF-Token.
    response.set_cookie(csrf_cookie_name(settings), issued.csrf_token, httponly=False, **common)  # type: ignore[arg-type]


def _clear_auth_cookies(response: Response, settings: Settings) -> None:
    for name in (session_cookie_name(settings), csrf_cookie_name(settings)):
        response.delete_cookie(name, path="/", secure=settings.secure_cookies, samesite="lax")


def _me(db: Session, user_id: uuid.UUID, is_admin: bool) -> MeOut:
    user = db.get_one(User, user_id)
    return MeOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        phone_e164=user.phone_e164,
        email_verified=user.email_verified_at is not None,
        is_admin=is_admin,
        created_at=user.created_at,
    )


@router.post("/auth/register", status_code=status.HTTP_202_ACCEPTED, response_model=Accepted)
def register(body: RegisterIn, request: Request, db: DbDep, settings: SettingsDep) -> Accepted:
    limit(request, rl.REGISTER_PER_IP, client_ip(request, settings))
    try:
        with atomic(db):
            accounts.register(
                db,
                settings,
                email=body.email,
                password=body.password,
                display_name=body.display_name.strip(),
            )
    except accounts.InvalidEmailError as exc:
        raise ApiError(422, "invalid_email", "email address is not valid") from exc
    except WeakPasswordError as exc:
        raise ApiError(422, "weak_password", str(exc)) from exc
    return Accepted()


@router.post("/auth/verify-email")
def verify_email(
    body: TokenIn, request: Request, db: DbDep, settings: SettingsDep
) -> dict[str, str]:
    limit(request, rl.TOKEN_ATTEMPT_PER_IP, client_ip(request, settings))
    try:
        with atomic(db):
            accounts.verify_email(db, token=body.token)
    except accounts.InvalidTokenError as exc:
        raise ApiError(400, "invalid_token", "link is invalid or expired") from exc
    return {"status": "verified"}


@router.post(
    "/auth/resend-verification", status_code=status.HTTP_202_ACCEPTED, response_model=Accepted
)
def resend_verification(
    body: EmailIn, request: Request, db: DbDep, settings: SettingsDep
) -> Accepted:
    limit(request, rl.EMAIL_ACTION_PER_IP, client_ip(request, settings))
    limit(request, rl.EMAIL_ACTION_PER_EMAIL, body.email.strip())
    with atomic(db):
        accounts.resend_verification(db, settings, email=body.email)
    return Accepted()


@router.post("/auth/login", response_model=MeOut)
def login(
    body: LoginIn, request: Request, response: Response, db: DbDep, settings: SettingsDep
) -> MeOut:
    ip = client_ip(request, settings)
    limit(request, rl.LOGIN_PER_IP, ip)
    limit(request, rl.LOGIN_PER_EMAIL, body.email.strip())
    try:
        with atomic(db):
            user = accounts.authenticate(db, email=body.email, password=body.password)
            issued = accounts.open_session(
                db,
                settings,
                user_id=user.id,
                user_agent=request.headers.get("user-agent", ""),
                ip=ip,
            )
            is_admin = db.get(Admin, user.id) is not None
            me = _me(db, user.id, is_admin)
    except accounts.InvalidCredentialsError as exc:
        raise ApiError(401, "invalid_credentials", "email or password is incorrect") from exc
    except accounts.AccountSuspendedError as exc:
        raise ApiError(403, "account_suspended", "this account is suspended") from exc
    _set_auth_cookies(response, settings, issued)
    return me


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(ctx: CurrentUser, response: Response, db: DbDep, settings: SettingsDep) -> Response:
    with atomic(db):
        sess = db.get_one(UserSession, ctx.session_id)
        sess.revoked_at = datetime.now().astimezone()
    _clear_auth_cookies(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post(
    "/auth/password-reset/request", status_code=status.HTTP_202_ACCEPTED, response_model=Accepted
)
def password_reset_request(
    body: EmailIn, request: Request, db: DbDep, settings: SettingsDep
) -> Accepted:
    limit(request, rl.EMAIL_ACTION_PER_IP, client_ip(request, settings))
    limit(request, rl.EMAIL_ACTION_PER_EMAIL, body.email.strip())
    with atomic(db):
        accounts.request_password_reset(db, settings, email=body.email)
    return Accepted()


@router.post("/auth/password-reset/confirm")
def password_reset_confirm(
    body: ResetConfirmIn, request: Request, db: DbDep, settings: SettingsDep
) -> dict[str, str]:
    limit(request, rl.TOKEN_ATTEMPT_PER_IP, client_ip(request, settings))
    try:
        with atomic(db):
            accounts.confirm_password_reset(db, token=body.token, new_password=body.new_password)
    except accounts.InvalidTokenError as exc:
        raise ApiError(400, "invalid_token", "link is invalid or expired") from exc
    except WeakPasswordError as exc:
        raise ApiError(422, "weak_password", str(exc)) from exc
    return {"status": "password_reset"}


@router.post("/auth/password/change")
def change_password(
    ctx: CurrentUser, body: ChangePasswordIn, request: Request, db: DbDep
) -> dict[str, str]:
    limit(request, rl.LOGIN_PER_EMAIL, ctx.email)
    try:
        with atomic(db):
            accounts.change_password(
                db,
                user_id=ctx.user_id,
                session_id=ctx.session_id,
                current=body.current_password,
                new=body.new_password,
            )
    except accounts.InvalidCredentialsError as exc:
        raise ApiError(400, "invalid_credentials", "current password is incorrect") from exc
    except WeakPasswordError as exc:
        raise ApiError(422, "weak_password", str(exc)) from exc
    return {"status": "password_changed"}


@router.get("/auth/me", response_model=MeOut)
def me(ctx: CurrentUser, db: DbDep) -> MeOut:
    return _me(db, ctx.user_id, ctx.is_admin)


@router.get("/auth/sessions", response_model=list[SessionOut])
def list_sessions(ctx: CurrentUser, db: DbDep) -> list[SessionOut]:
    now = datetime.now().astimezone()
    rows = db.scalars(
        select(UserSession)
        .where(
            UserSession.user_id == ctx.user_id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
        .order_by(UserSession.last_seen_at.desc())
    ).all()
    return [
        SessionOut(
            id=r.id,
            created_at=r.created_at,
            last_seen_at=r.last_seen_at,
            expires_at=r.expires_at,
            user_agent=r.user_agent,
            ip_address=r.ip_address,
            current=r.id == ctx.session_id,
        )
        for r in rows
    ]


@router.delete("/auth/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session(session_id: uuid.UUID, ctx: CurrentUser, db: DbDep) -> Response:
    with atomic(db):
        sess = db.get(UserSession, session_id)
        if sess is None or sess.user_id != ctx.user_id:  # never reveal others' sessions
            raise ApiError(404, "not_found", "session not found")
        if sess.revoked_at is None:
            sess.revoked_at = datetime.now().astimezone()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/auth/sessions/revoke-others")
def revoke_other_sessions(ctx: CurrentUser, db: DbDep) -> dict[str, str]:
    with atomic(db):
        accounts.revoke_sessions(db, ctx.user_id, keep=ctx.session_id)
    return {"status": "revoked"}


@router.patch("/me/profile", response_model=MeOut)
def update_profile(ctx: CurrentUser, body: ProfileIn, db: DbDep) -> MeOut:
    if (
        body.phone_e164 is not None
        and body.phone_e164 != ""
        and not PHONE_RE.match(body.phone_e164)
    ):
        raise ApiError(422, "invalid_phone", "phone must be in E.164 format, e.g. +97699112233")
    try:
        with atomic(db):
            user = db.get_one(User, ctx.user_id)
            if body.display_name is not None:
                user.display_name = body.display_name.strip()
            if body.phone_e164 is not None:
                user.phone_e164 = body.phone_e164 or None
    except IntegrityError as exc:
        raise ApiError(409, "phone_taken", "this phone number is already used") from exc
    return _me(db, ctx.user_id, ctx.is_admin)
