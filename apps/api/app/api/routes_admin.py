"""Administrator API — served ONLY by the separate admin-api process, which
connects as ``safepay_admin``. The public API never mounts these routes and
never holds admin database credentials.

Two independent checks guard every write: ``require_admin`` (session user is in
``admins``) here, and the ADMIN database functions, which re-check the
``admins`` table and refuse admins acting on their own deals.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.auth_context import AdminUser
from app.api.errors import ApiError
from app.api.routes_disputes import EvidenceOut, evidence_out, file_response
from app.db.session import get_db
from app.db.transactions import atomic
from app.domain.deal_states import DealStatus
from app.models import (
    Admin,
    AuditEvent,
    Deal,
    DealParticipant,
    Dispute,
    DisputeEvidence,
    DisputeOutcome,
    DisputeStatus,
    EvidenceKind,
    User,
    UserStatus,
)
from app.services import deal_transitions as dt
from app.services import disputes as dsvc

router = APIRouter(prefix="/admin", tags=["admin"])
DbDep = Annotated[Session, Depends(get_db)]


class OverviewOut(BaseModel):
    open_disputes: int
    users: int
    suspended_users: int
    deals_by_status: dict[str, int]


class ParticipantOut(BaseModel):
    user_id: uuid.UUID
    role: str
    display_name: str
    email: str
    status: UserStatus


class DisputeSummaryOut(BaseModel):
    id: uuid.UUID
    deal_id: uuid.UUID
    deal_reference: str
    deal_title: str
    amount_mnt: str
    status: DisputeStatus
    opened_at: datetime


class AdminDisputeOut(DisputeSummaryOut):
    reason: str
    opened_by_role: str
    deal_status: DealStatus
    resolved_at: datetime | None
    outcome: DisputeOutcome | None
    decision_reason: str | None
    participants: list[ParticipantOut]
    evidence: list[EvidenceOut]
    timeline: list[dict[str, Any]]


class DecisionIn(BaseModel):
    outcome: DisputeOutcome
    reason: str = Field(min_length=10, max_length=2000)


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    status: UserStatus
    email_verified: bool
    is_admin: bool
    created_at: datetime


class UserStatusIn(BaseModel):
    status: Literal["ACTIVE", "SUSPENDED"]
    reason: str = Field(min_length=5, max_length=2000)


class AuditOut(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    actor_type: str
    actor_user_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: uuid.UUID
    deal_id: uuid.UUID | None
    data: dict[str, Any]


_ADMIN_ERRORS: dict[type[dt.DealTransitionError], tuple[int, str]] = {
    dt.DealNotFoundError: (404, "not_found"),
    dt.TransitionNotAllowedError: (409, "action_not_allowed"),
    dt.NotAdministratorError: (403, "not_permitted"),
    dt.ReasonRequiredError: (422, "reason_required"),
    dt.EscrowInvariantError: (409, "escrow_invariant"),
    dt.ParticipantMismatchError: (409, "participants_incomplete"),
}


def _map(exc: dt.DealTransitionError) -> ApiError:
    status, code = _ADMIN_ERRORS.get(type(exc), (409, "action_not_allowed"))
    return ApiError(status, code, str(exc).removeprefix("SafePay: "))


@router.get("/overview", response_model=OverviewOut)
def overview(_: AdminUser, db: DbDep) -> OverviewOut:
    by_status = dict(db.execute(select(Deal.status, func.count()).group_by(Deal.status)).all())
    return OverviewOut(
        open_disputes=db.scalar(
            select(func.count()).select_from(Dispute).where(Dispute.status == DisputeStatus.OPEN)
        )
        or 0,
        users=db.scalar(select(func.count()).select_from(User)) or 0,
        suspended_users=db.scalar(
            select(func.count()).select_from(User).where(User.status == UserStatus.SUSPENDED)
        )
        or 0,
        deals_by_status={str(k.value): int(v) for k, v in by_status.items()},
    )


def _summary(d: Dispute, deal: Deal) -> DisputeSummaryOut:
    return DisputeSummaryOut(
        id=d.id,
        deal_id=deal.id,
        deal_reference=deal.reference,
        deal_title=deal.title,
        amount_mnt=str(deal.amount_mnt),
        status=d.status,
        opened_at=d.opened_at,
    )


@router.get("/disputes", response_model=list[DisputeSummaryOut])
def list_disputes(
    _: AdminUser, db: DbDep, status: Literal["OPEN", "RESOLVED", "ALL"] = "OPEN"
) -> list[DisputeSummaryOut]:
    stmt = select(Dispute, Deal).join(Deal, Deal.id == Dispute.deal_id)
    if status != "ALL":
        stmt = stmt.where(Dispute.status == status)
    rows = db.execute(stmt.order_by(Dispute.opened_at).limit(200)).all()
    return [_summary(d, deal) for d, deal in rows]


def _dispute_detail(db: Session, dispute_id: uuid.UUID) -> AdminDisputeOut:
    row = db.execute(
        select(Dispute, Deal).join(Deal, Deal.id == Dispute.deal_id).where(Dispute.id == dispute_id)
    ).one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "dispute not found")
    dispute, deal = row
    parts = db.execute(
        select(DealParticipant, User)
        .join(User, User.id == DealParticipant.user_id)
        .where(DealParticipant.deal_id == deal.id)
    ).all()
    roles = {p.user_id: p.role.value for p, _ in parts}
    evidence = db.scalars(
        select(DisputeEvidence)
        .where(DisputeEvidence.dispute_id == dispute_id)
        .order_by(DisputeEvidence.created_at)
    ).all()
    events = db.scalars(
        select(AuditEvent).where(AuditEvent.deal_id == deal.id).order_by(AuditEvent.occurred_at)
    ).all()
    return AdminDisputeOut(
        **_summary(dispute, deal).model_dump(),
        reason=dispute.reason,
        opened_by_role=roles.get(dispute.opened_by_id, "?"),
        deal_status=deal.status,
        resolved_at=dispute.resolved_at,
        outcome=dispute.outcome,
        decision_reason=dispute.decision_reason,
        participants=[
            ParticipantOut(
                user_id=u.id,
                role=p.role.value,
                display_name=u.display_name,
                email=u.email,
                status=u.status,
            )
            for p, u in parts
        ],
        evidence=[evidence_out(e, viewer=None, roles=roles) for e in evidence],
        timeline=[
            {
                "action": e.action,
                "actor": e.actor_type.value,
                "occurred_at": e.occurred_at.isoformat(),
                "data": {k: str(v) for k, v in e.data.items()},
            }
            for e in events
        ],
    )


@router.get("/disputes/{dispute_id}", response_model=AdminDisputeOut)
def get_dispute(dispute_id: uuid.UUID, _: AdminUser, db: DbDep) -> AdminDisputeOut:
    return _dispute_detail(db, dispute_id)


@router.get("/disputes/{dispute_id}/evidence/{evidence_id}/file")
def download(dispute_id: uuid.UUID, evidence_id: uuid.UUID, _: AdminUser, db: DbDep) -> Response:
    try:
        item = dsvc.load_file(db, dispute_id=dispute_id, evidence_id=evidence_id, user_id=None)
    except dsvc.DisputeNotVisibleError as exc:
        raise ApiError(404, "not_found", "file not found") from exc
    return file_response(item)


@router.post("/disputes/{dispute_id}/notes", response_model=AdminDisputeOut)
def add_note(dispute_id: uuid.UUID, body: NoteIn, ctx: AdminUser, db: DbDep) -> AdminDisputeOut:
    try:
        with atomic(db):
            db.add(
                DisputeEvidence(
                    dispute_id=dispute_id,
                    author_user_id=ctx.user_id,
                    kind=EvidenceKind.ADMIN_NOTE,
                    body=body.body.strip(),
                )
            )
            db.flush()
    except DBAPIError as exc:
        raise ApiError(409, "note_rejected", "dispute is closed or not found") from exc
    return _dispute_detail(db, dispute_id)


@router.post("/disputes/{dispute_id}/decision", response_model=AdminDisputeOut)
def decide(
    dispute_id: uuid.UUID, body: DecisionIn, ctx: AdminUser, request: Request, db: DbDep
) -> AdminDisputeOut:
    try:
        with atomic(db):
            dt.admin_resolve_dispute(
                db,
                dispute_id=dispute_id,
                outcome=body.outcome.value,
                admin_user_id=ctx.user_id,
                reason=body.reason,
                request_id=getattr(request.state, "request_id", None),
            )
    except dt.DealTransitionError as exc:
        raise _map(exc) from exc
    return _dispute_detail(db, dispute_id)


@router.get("/users", response_model=list[UserOut])
def users(_: AdminUser, db: DbDep, q: str = "") -> list[UserOut]:
    stmt = select(User).order_by(User.created_at.desc()).limit(100)
    if q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(User.email.like(like), func.lower(User.display_name).like(like)))
    admins = set(db.scalars(select(Admin.user_id)))
    return [
        UserOut(
            id=u.id,
            email=u.email,
            display_name=u.display_name,
            status=u.status,
            email_verified=u.email_verified_at is not None,
            is_admin=u.id in admins,
            created_at=u.created_at,
        )
        for u in db.scalars(stmt)
    ]


@router.post("/users/{user_id}/status", status_code=204)
def set_user_status(user_id: uuid.UUID, body: UserStatusIn, ctx: AdminUser, db: DbDep) -> Response:
    try:
        with atomic(db):
            dt.admin_set_user_status(
                db,
                admin_user_id=ctx.user_id,
                user_id=user_id,
                status=body.status,
                reason=body.reason,
            )
    except dt.DealTransitionError as exc:
        raise _map(exc) from exc
    return Response(status_code=204)


@router.get("/audit", response_model=list[AuditOut])
def audit(_: AdminUser, db: DbDep, limit: int = 100) -> list[AuditOut]:
    rows = db.scalars(
        select(AuditEvent).order_by(AuditEvent.occurred_at.desc()).limit(min(max(limit, 1), 500))
    ).all()
    return [
        AuditOut(
            id=e.id,
            occurred_at=e.occurred_at,
            actor_type=e.actor_type.value,
            actor_user_id=e.actor_user_id,
            action=e.action,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            deal_id=e.deal_id,
            data=e.data,
        )
        for e in rows
    ]
