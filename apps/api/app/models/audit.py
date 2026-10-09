"""Append-only audit trail. Rows can never be updated or deleted (DB trigger)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.deal_states import Actor
from app.models.base import Base, UUIDPrimaryKeyMixin, str_enum


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_entity", "entity_type", "entity_id", "occurred_at"),
        Index("ix_audit_events_deal_id_occurred_at", "deal_id", "occurred_at"),
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    actor_type: Mapped[Actor] = mapped_column(str_enum(Actor, "audit_actor_type"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    # e.g. "deal.status_changed", "ledger.transaction_posted"
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[uuid.UUID]
    deal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("deals.id", ondelete="RESTRICT"))
    request_id: Mapped[str | None] = mapped_column(String(64))
    # Never store secrets or full personal documents here.
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
