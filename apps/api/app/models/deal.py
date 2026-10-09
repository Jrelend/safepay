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
        Index("ix_deals_status", "status"),
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
