"""Stored results of idempotent operations (see ``app.services.idempotency``).

A record is claimed (inserted) at the start of an operation and completed in
the same database transaction. Once completed it is write-once: a trigger
rejects any further change, and the application role cannot delete it.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        CheckConstraint("length(key) > 0", name="key_not_empty"),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="request_hash_sha256"),
        CheckConstraint(
            "(completed_at IS NULL) = (response IS NULL)", name="completed_has_response"
        ),
    )

    # e.g. "deal.transition"; keys are unique per scope.
    scope: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    # SHA-256 of the canonical JSON request; a reused key with a different hash is rejected.
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
