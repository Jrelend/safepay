"""Disputes and evidence (public API, safepay_app).

Evidence is private: only the deal's two participants (here) and administrators
(admin API) can see it. It is append-only once submitted (DB trigger), and the
database independently checks that the author is a participant and that the
dispute is still open.
"""

import hashlib
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, undefer

from app.models import Deal, DealParticipant, Dispute, DisputeEvidence, EvidenceKind
from app.models.dispute import MAX_EVIDENCE_BYTES, MAX_EVIDENCE_TEXT

_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"%PDF-", "application/pdf"),
)
_UNSAFE_NAME = re.compile(r"[^\w.\- ]+", re.UNICODE)


class DisputeNotVisibleError(Exception):
    pass


class EvidenceRejectedError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class DisputeView:
    dispute: Dispute
    deal: Deal
    evidence: list[DisputeEvidence]


def _visible_dispute(db: Session, dispute_id: uuid.UUID, user_id: uuid.UUID) -> Dispute:
    dispute = db.get(Dispute, dispute_id)
    if dispute is None or not db.scalar(
        select(DealParticipant.user_id).where(
            DealParticipant.deal_id == dispute.deal_id, DealParticipant.user_id == user_id
        )
    ):
        raise DisputeNotVisibleError
    return dispute


def view(db: Session, *, dispute_id: uuid.UUID, user_id: uuid.UUID) -> DisputeView:
    dispute = _visible_dispute(db, dispute_id, user_id)
    evidence = list(
        db.scalars(
            select(DisputeEvidence)
            .where(
                DisputeEvidence.dispute_id == dispute_id,
                # Internal admin notes are never shown to participants.
                DisputeEvidence.kind != EvidenceKind.ADMIN_NOTE,
            )
            .order_by(DisputeEvidence.created_at)
        )
    )
    return DisputeView(dispute, db.get_one(Deal, dispute.deal_id), evidence)


def add_statement(
    db: Session, *, dispute_id: uuid.UUID, user_id: uuid.UUID, body: str
) -> DisputeEvidence:
    _visible_dispute(db, dispute_id, user_id)
    body = body.strip()
    if not 1 <= len(body) <= MAX_EVIDENCE_TEXT:
        raise EvidenceRejectedError("invalid_statement")
    item = DisputeEvidence(
        dispute_id=dispute_id, author_user_id=user_id, kind=EvidenceKind.STATEMENT, body=body
    )
    db.add(item)
    db.flush()
    return item


def sniff_content_type(data: bytes) -> str:
    for signature, content_type in _SIGNATURES:
        if data.startswith(signature):
            return content_type
    raise EvidenceRejectedError("unsupported_file_type")


def safe_file_name(name: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE_NAME.sub("_", base).strip(" .")[:100]
    return cleaned or "evidence"


def add_file(
    db: Session,
    *,
    dispute_id: uuid.UUID,
    user_id: uuid.UUID,
    file_name: str,
    data: bytes,
    caption: str,
) -> DisputeEvidence:
    _visible_dispute(db, dispute_id, user_id)
    if not 0 < len(data) <= MAX_EVIDENCE_BYTES:
        raise EvidenceRejectedError("file_too_large" if data else "empty_file")
    item = DisputeEvidence(
        dispute_id=dispute_id,
        author_user_id=user_id,
        kind=EvidenceKind.FILE,
        body=caption.strip()[:MAX_EVIDENCE_TEXT],
        file_name=safe_file_name(file_name),
        content_type=sniff_content_type(data),  # never trust the client's type
        file_size=len(data),
        file_sha256=hashlib.sha256(data).hexdigest(),
        file_data=data,
    )
    db.add(item)
    db.flush()
    return item


def load_file(
    db: Session, *, dispute_id: uuid.UUID, evidence_id: uuid.UUID, user_id: uuid.UUID | None
) -> DisputeEvidence:
    """``user_id=None`` is used only by the admin API (role-checked separately)."""
    if user_id is not None:
        _visible_dispute(db, dispute_id, user_id)
    item = db.scalar(
        select(DisputeEvidence)
        .options(undefer(DisputeEvidence.file_data))
        .where(
            DisputeEvidence.id == evidence_id,
            DisputeEvidence.dispute_id == dispute_id,
            DisputeEvidence.kind == EvidenceKind.FILE,
        )
    )
    if item is None or item.file_data is None:
        raise DisputeNotVisibleError
    return item
