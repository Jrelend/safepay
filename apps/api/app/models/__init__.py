"""SQLAlchemy ORM models. Importing this package registers every table on ``Base.metadata``."""

from app.models.audit import AuditEvent
from app.models.auth import AuthToken, EmailOutbox, RateLimit, TokenPurpose, UserSession
from app.models.base import Base
from app.models.deal import Deal, DealParticipant, ParticipantRole
from app.models.deal_transition import DealTransitionRule
from app.models.dispute import (
    Dispute,
    DisputeEvidence,
    DisputeOutcome,
    DisputeStatus,
    EvidenceKind,
    Notification,
)
from app.models.idempotency import IdempotencyRecord
from app.models.ledger import LedgerAccount, LedgerEntry, LedgerTransaction
from app.models.policy import PlatformPolicy
from app.models.user import Admin, User, UserStatus

__all__ = [
    "Admin",
    "AuditEvent",
    "AuthToken",
    "Base",
    "Deal",
    "DealParticipant",
    "DealTransitionRule",
    "Dispute",
    "DisputeEvidence",
    "DisputeOutcome",
    "DisputeStatus",
    "EmailOutbox",
    "EvidenceKind",
    "IdempotencyRecord",
    "LedgerAccount",
    "LedgerEntry",
    "LedgerTransaction",
    "Notification",
    "ParticipantRole",
    "PlatformPolicy",
    "RateLimit",
    "TokenPurpose",
    "User",
    "UserSession",
    "UserStatus",
]
