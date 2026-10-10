"""Account lifecycle. Every function runs inside the caller's ``atomic`` block.

Enumeration resistance: register, resend-verification and reset-request do the
same work and return the same result whether or not the email is known.
Emails are *simulated* (written to ``email_outbox``), never sent.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import (
    check_password_policy,
    hash_password,
    needs_rehash,
    new_token,
    sha256_hex,
    verify_password,
)
from app.models import AuthToken, EmailOutbox, TokenPurpose, User, UserSession, UserStatus

VERIFY_TTL = timedelta(hours=24)
RESET_TTL = timedelta(hours=1)


class InvalidEmailError(ValueError):
    pass


class InvalidTokenError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class AccountSuspendedError(Exception):
    pass


def normalize_email(raw: str) -> str:
    try:
        info = validate_email(raw.strip(), check_deliverability=False)
    except EmailNotValidError as exc:
        raise InvalidEmailError(str(exc)) from exc
    return info.normalized.lower()


def _outbox(db: Session, to: str, template: str, data: dict[str, Any]) -> None:
    db.add(EmailOutbox(to_email=to, template=template, data=data))


def _issue_token(db: Session, user_id: uuid.UUID, purpose: TokenPurpose, ttl: timedelta) -> str:
    raw = new_token()
    db.add(
        AuthToken(
            user_id=user_id,
            purpose=purpose,
            token_hash=sha256_hex(raw),
            expires_at=datetime.now(UTC) + ttl,
        )
    )
    return raw


def register(
    db: Session, settings: Settings, *, email: str, password: str, display_name: str
) -> None:
    email = normalize_email(email)
    check_password_policy(password, email=email)
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        # Same visible outcome as a new registration; the owner is told by email.
        hash_password(password)  # keep timing comparable
        _outbox(db, email, "account_exists", {"login_url": f"{settings.public_web_url}/login"})
        return
    user = User(email=email, password_hash=hash_password(password), display_name=display_name)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:  # concurrent registration of the same email
        db.rollback()
        return
    raw = _issue_token(db, user.id, TokenPurpose.VERIFY_EMAIL, VERIFY_TTL)
    _outbox(
        db,
        email,
        "verify_email",
        {"name": display_name, "link": f"{settings.public_web_url}/verify-email?token={raw}"},
    )


def resend_verification(db: Session, settings: Settings, *, email: str) -> None:
    try:
        email = normalize_email(email)
    except InvalidEmailError:
        return
    user = db.scalar(select(User).where(User.email == email))
    if user is None or user.email_verified_at is not None:
        return
    raw = _issue_token(db, user.id, TokenPurpose.VERIFY_EMAIL, VERIFY_TTL)
    _outbox(
        db,
        email,
        "verify_email",
        {"name": user.display_name, "link": f"{settings.public_web_url}/verify-email?token={raw}"},
    )


def _consume_token(db: Session, raw: str, purpose: TokenPurpose) -> AuthToken:
    token = db.scalar(
        select(AuthToken)
        .where(AuthToken.token_hash == sha256_hex(raw), AuthToken.purpose == purpose)
        .with_for_update()
    )
    if token is None or token.used_at is not None or token.expires_at <= datetime.now(UTC):
        raise InvalidTokenError
    token.used_at = datetime.now(UTC)
    return token


def _retire_tokens(db: Session, user_id: uuid.UUID, purpose: TokenPurpose) -> None:
    """Invalidate every outstanding one-time token of ``purpose`` for the user."""
    db.flush()  # persist the token just consumed first (its used_at is write-once)
    db.execute(
        update(AuthToken)
        .where(
            AuthToken.user_id == user_id,
            AuthToken.purpose == purpose,
            AuthToken.used_at.is_(None),
        )
        .values(used_at=datetime.now(UTC))
    )


def verify_email(db: Session, *, token: str) -> None:
    record = _consume_token(db, token, TokenPurpose.VERIFY_EMAIL)
    user = db.get_one(User, record.user_id)
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
        _retire_tokens(db, user.id, TokenPurpose.VERIFY_EMAIL)
        # Whoever registered the address may have signed in before its owner proved
        # control of it; those pre-verification sessions do not survive verification.
        revoke_sessions(db, user.id)


def request_password_reset(db: Session, settings: Settings, *, email: str) -> None:
    try:
        email = normalize_email(email)
    except InvalidEmailError:
        return
    user = db.scalar(select(User).where(User.email == email))
    if user is None or user.status is not UserStatus.ACTIVE:
        return
    raw = _issue_token(db, user.id, TokenPurpose.RESET_PASSWORD, RESET_TTL)
    _outbox(
        db,
        email,
        "password_reset",
        {
            "name": user.display_name,
            "link": f"{settings.public_web_url}/reset-password?token={raw}",
        },
    )


def revoke_sessions(db: Session, user_id: uuid.UUID, *, keep: uuid.UUID | None = None) -> None:
    stmt = update(UserSession).where(
        UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
    )
    if keep is not None:
        stmt = stmt.where(UserSession.id != keep)
    db.execute(stmt.values(revoked_at=datetime.now(UTC)))


def confirm_password_reset(db: Session, *, token: str, new_password: str) -> None:
    record = _consume_token(db, token, TokenPurpose.RESET_PASSWORD)
    user = db.get_one(User, record.user_id)
    check_password_policy(new_password, email=user.email)
    user.password_hash = hash_password(new_password)
    # A reset also proves control of the mailbox.
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
    revoke_sessions(db, user.id)
    _retire_tokens(db, user.id, TokenPurpose.RESET_PASSWORD)
    _outbox(db, user.email, "password_changed", {"name": user.display_name})


def change_password(
    db: Session, *, user_id: uuid.UUID, session_id: uuid.UUID, current: str, new: str
) -> None:
    user = db.get_one(User, user_id)
    if not verify_password(user.password_hash, current):
        raise InvalidCredentialsError
    check_password_policy(new, email=user.email)
    user.password_hash = hash_password(new)
    revoke_sessions(db, user.id, keep=session_id)
    _retire_tokens(db, user.id, TokenPurpose.RESET_PASSWORD)
    _outbox(db, user.email, "password_changed", {"name": user.display_name})


@dataclass(frozen=True, slots=True)
class IssuedSession:
    session_id: uuid.UUID
    token: str
    csrf_token: str
    expires_at: datetime


def authenticate(db: Session, *, email: str, password: str) -> User:
    try:
        email = normalize_email(email)
    except InvalidEmailError:
        verify_password(None, password)
        raise InvalidCredentialsError from None
    user = db.scalar(select(User).where(User.email == email))
    if not verify_password(user.password_hash if user else None, password) or user is None:
        raise InvalidCredentialsError
    if user.status is not UserStatus.ACTIVE:
        raise AccountSuspendedError
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user


def open_session(
    db: Session, settings: Settings, *, user_id: uuid.UUID, user_agent: str, ip: str
) -> IssuedSession:
    token, csrf = new_token(), new_token()
    expires = datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours)
    sess = UserSession(
        token_hash=sha256_hex(token),
        csrf_hash=sha256_hex(csrf),
        user_id=user_id,
        expires_at=expires,
        user_agent=user_agent[:255],
        ip_address=ip[:64],
    )
    db.add(sess)
    db.flush()
    return IssuedSession(sess.id, token, csrf, expires)
