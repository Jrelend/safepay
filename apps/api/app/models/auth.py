"""Sessions, one-time tokens, the simulated email outbox and rate-limit counters."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin, str_enum

SHA256_HEX = "~ '^[0-9a-f]{64}$'"


class UserSession(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(f"token_hash {SHA256_HEX}", name="token_hash_sha256"),
        CheckConstraint(f"csrf_hash {SHA256_HEX}", name="csrf_hash_sha256"),
        CheckConstraint("expires_at > created_at", name="expires_after_creation"),
        Index("ix_sessions_user_id", "user_id"),
    )

    # Only SHA-256 hashes are stored; the raw tokens live in the browser cookies.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str] = mapped_column(String(255), default="", server_default="")
    ip_address: Mapped[str] = mapped_column(String(64), default="", server_default="")


class AdminSession(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Admin-API sessions: a separate store that only ``safepay_admin`` can write."""

    __tablename__ = "admin_sessions"
    __table_args__ = (
        CheckConstraint(f"token_hash {SHA256_HEX}", name="token_hash_sha256"),
        CheckConstraint(f"csrf_hash {SHA256_HEX}", name="csrf_hash_sha256"),
        CheckConstraint("expires_at > created_at", name="expires_after_creation"),
        Index("ix_admin_sessions_admin_user_id", "admin_user_id"),
    )

    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    admin_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("admins.user_id", ondelete="CASCADE")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str] = mapped_column(String(255), default="", server_default="")
    ip_address: Mapped[str] = mapped_column(String(64), default="", server_default="")


class TokenPurpose(StrEnum):
    VERIFY_EMAIL = "VERIFY_EMAIL"
    RESET_PASSWORD = "RESET_PASSWORD"  # noqa: S105 - enum label, not a secret


class AuthToken(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "auth_tokens"
    __table_args__ = (
        CheckConstraint(f"token_hash {SHA256_HEX}", name="token_hash_sha256"),
        Index("ix_auth_tokens_user_id_purpose", "user_id", "purpose"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    purpose: Mapped[TokenPurpose] = mapped_column(str_enum(TokenPurpose, "token_purpose"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailOutbox(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Simulated email. Nothing is ever sent; rows are purged by the worker."""

    __tablename__ = "email_outbox"

    to_email: Mapped[str] = mapped_column(String(254), index=True)
    template: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")


class RateLimit(Base):
    __tablename__ = "rate_limits"

    bucket: Mapped[str] = mapped_column(String(64), primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
