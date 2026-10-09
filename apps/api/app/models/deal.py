import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.deal_states import DealStatus
from app.domain.deal_terms import (
    DEFAULT_INSPECTION_DAYS,
    MAX_INSPECTION_DAYS,
    MIN_INSPECTION_DAYS,
    DeliveryMethod,
    ItemType,
)
from app.domain.money import CURRENCY
from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin, str_enum


class ParticipantRole(StrEnum):
    BUYER = "BUYER"
    SELLER = "SELLER"


class Deal(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """An escrow agreement between exactly one buyer and one seller."""

    __tablename__ = "deals"
    __table_args__ = (
        CheckConstraint("amount_mnt > 0", name="amount_positive"),
        CheckConstraint(f"currency = '{CURRENCY}'", name="currency_mnt"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            f"inspection_days BETWEEN {MIN_INSPECTION_DAYS} AND {MAX_INSPECTION_DAYS}",
            name="inspection_days_range",
        ),
        CheckConstraint("char_length(title) BETWEEN 3 AND 200", name="title_length"),
        CheckConstraint("invite_token_hash ~ '^[0-9a-f]{64}$'", name="invite_token_sha256"),
        CheckConstraint(
            "invite_email IS NULL OR invite_email = lower(invite_email)",
            name="invite_email_normalized",
        ),
        Index("ix_deals_status", "status"),
        Index("ix_deals_status_status_changed_at", "status", "status_changed_at"),
    )

    # Short human-friendly reference shown in the UI (e.g. SP-7KQ2M9).
    reference: Mapped[str] = mapped_column(String(16), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    amount_mnt: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default=CURRENCY, server_default=CURRENCY)
    status: Mapped[DealStatus] = mapped_column(
        str_enum(DealStatus, "deal_status"), default=DealStatus.DRAFT
    )
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    item_type: Mapped[ItemType] = mapped_column(
        str_enum(ItemType, "item_type"),
        default=ItemType.PHYSICAL_GOODS,
        server_default=ItemType.PHYSICAL_GOODS.value,
    )
    delivery_method: Mapped[DeliveryMethod] = mapped_column(
        str_enum(DeliveryMethod, "delivery_method"),
        default=DeliveryMethod.FACE_TO_FACE,
        server_default=DeliveryMethod.FACE_TO_FACE.value,
    )
    # Days the buyer has to inspect after delivery before SYSTEM auto-releases.
    inspection_days: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_INSPECTION_DAYS, server_default=str(DEFAULT_INSPECTION_DAYS)
    )
    # SHA-256 of the share-link token; the raw token is shown once to the creator.
    invite_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # Optional: only this (normalized) email may join via the link.
    invite_email: Mapped[str | None] = mapped_column(String(254))
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    # Optimistic concurrency control: every state change must bump the version.
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    participants: Mapped[list["DealParticipant"]] = relationship(back_populates="deal")

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012


class DealParticipant(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "deal_participants"
    __table_args__ = (
        UniqueConstraint("deal_id", "role"),
        UniqueConstraint("deal_id", "user_id"),
    )

    deal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("deals.id", ondelete="RESTRICT"))
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    role: Mapped[ParticipantRole] = mapped_column(str_enum(ParticipantRole, "participant_role"))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    deal: Mapped[Deal] = relationship(back_populates="participants")
