"""Who is calling? Derived ONLY from the server-side session.

* The session cookie holds an opaque token; the DB stores its SHA-256.
* Unsafe requests must carry ``X-CSRF-Token`` whose SHA-256 equals the
  session's ``csrf_hash`` (synchronizer token), on top of the Origin check
  done in middleware for every unsafe request.
* No endpoint accepts a user id or actor from the client.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select, update

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.security import constant_time_equals, sha256_hex
from app.models import Admin, User, UserSession, UserStatus

CSRF_HEADER = "X-CSRF-Token"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
TOUCH_INTERVAL = timedelta(minutes=5)


def session_cookie_name(settings: Settings) -> str:
    # __Host- cookies must be Secure, host-only and Path=/ (browser-enforced).
    return "__Host-safepay_session" if settings.secure_cookies else "safepay_session"


def csrf_cookie_name(settings: Settings) -> str:
    return "__Host-safepay_csrf" if settings.secure_cookies else "safepay_csrf"


@dataclass(frozen=True, slots=True)
class AuthContext:
    user_id: uuid.UUID
    session_id: uuid.UUID
    email: str
    display_name: str
    email_verified: bool
    is_admin: bool


def client_ip(request: Request, settings: Settings) -> str:
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def _load(request: Request) -> AuthContext | None:
    settings: Settings = request.app.state.settings
    token = request.cookies.get(session_cookie_name(settings))
    if not token or len(token) > 256:
        return None
    now = datetime.now(UTC)
    with request.app.state.sessionmaker() as db:
        row = db.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.token_hash == sha256_hex(token))
        ).one_or_none()
        if row is None:
            return None
        sess, user = row
        idle_limit = timedelta(hours=settings.session_idle_hours)
        if (
            sess.revoked_at is not None
            or sess.expires_at <= now
            or sess.last_seen_at + idle_limit <= now
            or user.status is not UserStatus.ACTIVE
        ):
            return None
        if request.method in UNSAFE_METHODS:
            supplied = request.headers.get(CSRF_HEADER, "")
            if not supplied or not constant_time_equals(sha256_hex(supplied), sess.csrf_hash):
                raise ApiError(403, "csrf_failed", "missing or invalid CSRF token")
        is_admin = db.scalar(select(Admin.user_id).where(Admin.user_id == user.id)) is not None
        ctx = AuthContext(
            user_id=user.id,
            session_id=sess.id,
            email=user.email,
            display_name=user.display_name,
            email_verified=user.email_verified_at is not None,
            is_admin=is_admin,
        )
        touch = settings.api_mode == "public" and now - sess.last_seen_at > TOUCH_INTERVAL
    if touch:
        with request.app.state.engine.begin() as conn:
            conn.execute(
                update(UserSession).where(UserSession.id == ctx.session_id).values(last_seen_at=now)
            )
    return ctx


def optional_user(request: Request) -> AuthContext | None:
    return _load(request)


def require_user(request: Request) -> AuthContext:
    ctx = _load(request)
    if ctx is None:
        raise ApiError(401, "not_authenticated", "sign in required")
    return ctx


def require_verified_user(ctx: Annotated[AuthContext, Depends(require_user)]) -> AuthContext:
    if not ctx.email_verified:
        raise ApiError(403, "email_not_verified", "verify your email address first")
    return ctx


def require_admin(ctx: Annotated[AuthContext, Depends(require_user)]) -> AuthContext:
    # Re-checked inside every admin DB function against the admins table.
    if not ctx.is_admin:
        raise ApiError(403, "not_admin", "administrator access required")
    return ctx


CurrentUser = Annotated[AuthContext, Depends(require_user)]
VerifiedUser = Annotated[AuthContext, Depends(require_verified_user)]
AdminUser = Annotated[AuthContext, Depends(require_admin)]
MaybeUser = Annotated[AuthContext | None, Depends(optional_user)]
