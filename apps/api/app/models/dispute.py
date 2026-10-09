import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin, str_enum

MAX_EVIDENCE_BYTES = 2 * 1024 * 1024
MAX_EVIDENCE_TEXT = 5000


class DisputeStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class DisputeOutcome(StrEnum):
    RELEASE_TO_SELLER = "RELEASE_TO_SELLER"
    REFUND_TO_BUYER = "REFUND_TO_BUYER"


class EvidenceKind(StrEnum):
    STATEMENT = "STATEMENT"
    FILE = "FILE"
    ADMIN_NOTE = "ADMIN_NOTE"


class Dispute(UUIDPrimaryKeyMixin, Base):
    """Created only by the transition function (OPEN_DISPUTE); resolved only by an admin."""

    __tablename__ = "disputes"
    __table_args__ = (
        CheckConstraint(
            "(status = 'OPEN') = "
            "(resolved_at IS NULL AND outcome IS NULL AND decided_by_id IS NULL)",
            name="resolution_consistent",
        ),
        Index("ix_disputes_status_opened_at", "status", "opened_at"),
    )

    deal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("deals.id", ondelete="RESTRICT"), unique=True
    )
    opened_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[DisputeStatus] = mapped_column(
        str_enum(DisputeStatus, "dispute_status"), default=DisputeStatus.OPEN
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[DisputeOutcome | None] = mapped_column(
        str_enum(DisputeOutcome, "dispute_outcome")
    )
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    decision_reason: Mapped[str | None] = mapped_column(Text)


class DisputeEvidence(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Append-only. Visible only to the deal's participants and to administrators."""

    __tablename__ = "dispute_evidence"
    __table_args__ = (
        CheckConstraint(f"char_length(body) <= {MAX_EVIDENCE_TEXT}", name="body_length"),
        CheckConstraint("(kind = 'FILE') = (file_data IS NOT NULL)", name="file_kind_has_data"),
        CheckConstraint(
            f"file_data IS NULL OR (octet_length(file_data) BETWEEN 1 AND {MAX_EVIDENCE_BYTES}"
            " AND file_size = octet_length(file_data)"
            " AND content_type IN ('image/png', 'image/jpeg', 'application/pdf'))",
            name="file_limits",
        ),
        Index("ix_dispute_evidence_dispute_id_created_at", "dispute_id", "created_at"),
    )

    dispute_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("disputes.id", ondelete="RESTRICT"))
    author_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    kind: Mapped[EvidenceKind] = mapped_column(str_enum(EvidenceKind, "evidence_kind"))
    body: Mapped[str] = mapped_column(Text, default="", server_default="")
    file_name: Mapped[str | None] = mapped_column(String(200))
    content_type: Mapped[str | None] = mapped_column(String(64))
    file_size: Mapped[int | None] = mapped_column(Integer)
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    file_data: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)


class Notification(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_id_created_at", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(64))
    deal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("deals.id", ondelete="RESTRICT"))
    data: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
