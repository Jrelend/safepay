"""Admin-API authentication: a separate login, credential and session store.

The public API's sessions and passwords are writable by ``safepay_app``; trusting
them here would let a public-API compromise become an admin. So the admin API:

* authenticates with an **admin-only password + TOTP code** (``admins`` columns
  only ``safepay_admin`` can read; set by the owner CLI);
* keeps sessions in ``admin_sessions`` (only ``safepay_admin`` can write), with a
  short absolute and idle lifetime and its own cookies and CSRF token;
* never reads the public ``sessions`` table.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app.api.auth_context import CSRF_HEADER, UNSAFE_METHODS, AuthContext, client_ip
from app.api.deps import SettingsDep
from app.api.errors import ApiError
from app.core import totp
from app.core.config import Settings
from app.core.security import constant_time_equals, new_token, sha256_hex, verify_password
from app.models import Admin, AdminSession, User, UserStatus
from app.services import rate_limit as rl
from app.services.accounts import InvalidEmailError, normalize_email

router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])
TOUCH_INTERVAL = timedelta(minutes=1)


def admin_cookie_name(settings: Settings) -> str:
    return "__Host-safepay_admin" if settings.secure_cookies else "safepay_admin"


def admin_csrf_cookie_name(settings: Settings) -> str:
    return "__Host-safepay_admin_csrf" if settings.secure_cookies else "safepay_admin_csrf"


class AdminLoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)
    code: str = Field(max_length=8)


class AdminMeOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    session_expires_at: datetime


def _limit(request: Request, limit_: rl.Limit, key: str) -> None:
    try:
        rl.hit(request.app.state.engine, limit_, key)
    except rl.RateLimitedError as exc:
        raise ApiError(429, "rate_limited", "too many attempts, try again later") from exc


_INVALID = ApiError(401, "invalid_credentials", "invalid email, password or code")


@router.post("/login", response_model=AdminMeOut)
def login(
    body: AdminLoginIn, request: Request, response: Response, settings: SettingsDep
) -> AdminMeOut:
    ip = client_ip(request, settings)
    _limit(request, rl.ADMIN_LOGIN_PER_IP, ip)
    try:
        email = normalize_email(body.email)
    except InvalidEmailError:
        email = body.email.strip().lower()
    _limit(request, rl.ADMIN_LOGIN_PER_EMAIL, email)
    now = datetime.now(UTC)
    with request.app.state.sessionmaker() as db:
        row = db.execute(
            select(User, Admin).join(Admin, Admin.user_id == User.id).where(User.email == email)
        ).one_or_none()
        user, admin = row if row else (None, None)
        # Always run one Argon2 verification so timing doesn't reveal admin emails.
        password_ok = verify_password(admin.password_hash if admin else None, body.password)
        if (
            user is None
            or admin is None
            or not password_ok
            or admin.totp_secret is None
            or user.status is not UserStatus.ACTIVE
            or user.email_verified_at is None
        ):
            raise _INVALID
        step = totp.verify(admin.totp_secret, body.code, last_used_step=admin.totp_last_step)
        if step is None:
            raise _INVALID
        # Consume the step atomically: a concurrent replay of the same code loses.
        used = db.execute(
            update(Admin)
            .where(Admin.user_id == admin.user_id, Admin.totp_last_step < step)
            .values(totp_last_step=step)
        )
        if used.rowcount != 1:
            db.rollback()
            raise _INVALID
        token, csrf = new_token(), new_token()
        expires = now + timedelta(hours=settings.admin_session_ttl_hours)
        db.add(
            AdminSession(
                token_hash=sha256_hex(token),
                csrf_hash=sha256_hex(csrf),
                admin_user_id=admin.user_id,
                expires_at=expires,
                user_agent=request.headers.get("user-agent", "")[:255],
                ip_address=ip,
            )
        )
        db.commit()
        out = AdminMeOut(
            id=user.id, email=user.email, display_name=user.display_name, session_expires_at=expires
        )
    common = {
        "secure": settings.secure_cookies,
        "samesite": "strict",
        "path": "/",
        "max_age": settings.admin_session_ttl_hours * 3600,
    }
    response.set_cookie(admin_cookie_name(settings), token, httponly=True, **common)  # type: ignore[arg-type]
    response.set_cookie(admin_csrf_cookie_name(settings), csrf, httponly=False, **common)  # type: ignore[arg-type]
    return out


def _load(request: Request) -> tuple[AuthContext, datetime] | None:
    settings: Settings = request.app.state.settings
    token = request.cookies.get(admin_cookie_name(settings))
    if not token or len(token) > 256:
        return None
    now = datetime.now(UTC)
    with request.app.state.sessionmaker() as db:
        row = db.execute(
            select(AdminSession, User)
            .join(Admin, Admin.user_id == AdminSession.admin_user_id)
            .join(User, User.id == Admin.user_id)
            .where(AdminSession.token_hash == sha256_hex(token))
        ).one_or_none()
        if row is None:
            return None
        sess, user = row
        idle = timedelta(minutes=settings.admin_session_idle_minutes)
        if (
            sess.revoked_at is not None
            or sess.expires_at <= now
            or sess.last_seen_at + idle <= now
            or user.status is not UserStatus.ACTIVE
        ):
            return None
        if request.method in UNSAFE_METHODS:
            supplied = request.headers.get(CSRF_HEADER, "")
            if not supplied or not constant_time_equals(sha256_hex(supplied), sess.csrf_hash):
                raise ApiError(403, "csrf_failed", "missing or invalid CSRF token")
        ctx = AuthContext(
            user_id=user.id,
            session_id=sess.id,
            email=user.email,
            display_name=user.display_name,
            email_verified=True,
            is_admin=True,
        )
        if now - sess.last_seen_at > TOUCH_INTERVAL:
            db.execute(
                update(AdminSession).where(AdminSession.id == sess.id).values(last_seen_at=now)
            )
            db.commit()
        return ctx, sess.expires_at


def require_admin(request: Request) -> AuthContext:
    loaded = _load(request)
    if loaded is None:
        raise ApiError(401, "not_authenticated", "admin sign-in required")
    return loaded[0]


AdminUser = Annotated[AuthContext, Depends(require_admin)]


@router.get("/me", response_model=AdminMeOut)
def me(request: Request) -> AdminMeOut:
    loaded = _load(request)
    if loaded is None:
        raise ApiError(401, "not_authenticated", "admin sign-in required")
    ctx, expires = loaded
    return AdminMeOut(
        id=ctx.user_id, email=ctx.email, display_name=ctx.display_name, session_expires_at=expires
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(ctx: AdminUser, request: Request, settings: SettingsDep) -> Response:
    with request.app.state.sessionmaker() as db:
        db.execute(
            update(AdminSession)
            .where(AdminSession.id == ctx.session_id, AdminSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    for name in (admin_cookie_name(settings), admin_csrf_cookie_name(settings)):
        response.delete_cookie(name, path="/", secure=settings.secure_cookies, samesite="strict")
    return response
