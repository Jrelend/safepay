import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin, str_enum


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class User(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        # Emails are stored normalized (lower-case) so uniqueness is case-insensitive.
        CheckConstraint(
            "email = lower(email) AND position('@' in email) > 1", name="email_normalized"
        ),
    )

    email: Mapped[str] = mapped_column(String(254), unique=True)
    # Argon2id PHC string. Never returned by any API.
    password_hash: Mapped[str] = mapped_column(Text)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Optional E.164 phone number (e.g. +97699112233), shown to the counterparty.
    phone_e164: Mapped[str | None] = mapped_column(String(16), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[UserStatus] = mapped_column(
        str_enum(UserStatus, "user_status"), default=UserStatus.ACTIVE
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Admin(Base):
    """Explicit administrator grants. Created only by the ops CLI (schema owner)."""

    __tablename__ = "admins"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    note: Mapped[str] = mapped_column(String(200), default="", server_default="")
    # Separate admin credentials (set only by the ops CLI). The public API role cannot
    # read or write these columns, so a public-API compromise cannot become admin.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    # Last TOTP time step accepted: each code works once (replay protection).
    totp_last_step: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
