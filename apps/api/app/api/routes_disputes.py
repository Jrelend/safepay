"""Dispute details and evidence (public API). Opening a dispute is the
OPEN_DISPUTE action on ``/deals/{id}/actions`` (with a reason in ``note``)."""

import uuid
from datetime import datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.auth_context import CurrentUser, VerifiedUser
from app.api.errors import ApiError
from app.api.routes_auth import limit
from app.db.session import get_db
from app.db.transactions import atomic
from app.models import (
    DealParticipant,
    DisputeEvidence,
    DisputeOutcome,
    DisputeStatus,
    EvidenceKind,
)
from app.models.dispute import MAX_EVIDENCE_BYTES
from app.services import disputes as svc
from app.services import rate_limit as rl

router = APIRouter(tags=["disputes"])
DbDep = Annotated[Session, Depends(get_db)]


class EvidenceOut(BaseModel):
    id: uuid.UUID
    kind: EvidenceKind
    mine: bool
    author_role: str
    body: str
    file_name: str | None
    content_type: str | None
    file_size: int | None
    created_at: datetime


class DisputeOut(BaseModel):
    id: uuid.UUID
    deal_id: uuid.UUID
    deal_reference: str
    deal_title: str
    status: DisputeStatus
    reason: str
    opened_by_me: bool
    opened_at: datetime
    resolved_at: datetime | None
    outcome: DisputeOutcome | None
    decision_reason: str | None
    evidence: list[EvidenceOut]


class StatementIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


def evidence_out(
    item: DisputeEvidence, *, viewer: uuid.UUID | None, roles: dict[uuid.UUID, str]
) -> EvidenceOut:
    return EvidenceOut(
        id=item.id,
        kind=item.kind,
        mine=item.author_user_id == viewer,
        author_role=roles.get(item.author_user_id, "ADMIN"),
        body=item.body,
        file_name=item.file_name,
        content_type=item.content_type,
        file_size=item.file_size,
        created_at=item.created_at,
    )


def _roles(db: Session, deal_id: uuid.UUID) -> dict[uuid.UUID, str]:
    return {
        uid: role.value
        for uid, role in db.execute(
            select(DealParticipant.user_id, DealParticipant.role).where(
                DealParticipant.deal_id == deal_id
            )
        ).all()
    }


def _out(db: Session, v: svc.DisputeView, user_id: uuid.UUID) -> DisputeOut:
    roles = _roles(db, v.deal.id)
    return DisputeOut(
        id=v.dispute.id,
        deal_id=v.deal.id,
        deal_reference=v.deal.reference,
        deal_title=v.deal.title,
        status=v.dispute.status,
        reason=v.dispute.reason,
        opened_by_me=v.dispute.opened_by_id == user_id,
        opened_at=v.dispute.opened_at,
        resolved_at=v.dispute.resolved_at,
        outcome=v.dispute.outcome,
        decision_reason=v.dispute.decision_reason,
        evidence=[evidence_out(e, viewer=user_id, roles=roles) for e in v.evidence],
    )


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "dispute not found")


@router.get("/disputes/{dispute_id}", response_model=DisputeOut)
def get_dispute(dispute_id: uuid.UUID, ctx: CurrentUser, db: DbDep) -> DisputeOut:
    try:
        return _out(db, svc.view(db, dispute_id=dispute_id, user_id=ctx.user_id), ctx.user_id)
    except svc.DisputeNotVisibleError as exc:
        raise _not_found() from exc


def _evidence_db_error(exc: DBAPIError) -> ApiError:
    if "open dispute" in str(exc.orig):
        return ApiError(409, "dispute_closed", "this dispute is closed")
    return ApiError(403, "evidence_rejected", "evidence rejected")


@router.post("/disputes/{dispute_id}/statements", response_model=DisputeOut)
def add_statement(
    dispute_id: uuid.UUID, body: StatementIn, ctx: VerifiedUser, request: Request, db: DbDep
) -> DisputeOut:
    limit(request, rl.EVIDENCE_PER_USER, str(ctx.user_id))
    try:
        with atomic(db):
            svc.add_statement(db, dispute_id=dispute_id, user_id=ctx.user_id, body=body.body)
    except svc.DisputeNotVisibleError as exc:
        raise _not_found() from exc
    except svc.EvidenceRejectedError as exc:
        status = 409 if exc.code == "evidence_limit" else 422
        raise ApiError(status, exc.code, "statement rejected") from exc
    except DBAPIError as exc:
        raise _evidence_db_error(exc) from exc
    return get_dispute(dispute_id, ctx, db)


@router.post("/disputes/{dispute_id}/files", response_model=DisputeOut)
async def add_file(
    dispute_id: uuid.UUID,
    ctx: VerifiedUser,
    request: Request,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    caption: Annotated[str, Form(max_length=1000)] = "",
) -> DisputeOut:
    limit(request, rl.EVIDENCE_PER_USER, str(ctx.user_id))
    data = await file.read(MAX_EVIDENCE_BYTES + 1)
    try:
        with atomic(db):
            svc.add_file(
                db,
                dispute_id=dispute_id,
                user_id=ctx.user_id,
                file_name=file.filename or "evidence",
                data=data,
                caption=caption,
            )
    except svc.DisputeNotVisibleError as exc:
        raise _not_found() from exc
    except svc.EvidenceRejectedError as exc:
        status = {"file_too_large": 413, "evidence_limit": 409}.get(exc.code, 422)
        raise ApiError(status, exc.code, "file rejected") from exc
    except DBAPIError as exc:
        raise _evidence_db_error(exc) from exc
    return get_dispute(dispute_id, ctx, db)


def file_response(item: DisputeEvidence) -> Response:
    if item.file_data is None:
        raise ApiError(404, "not_found", "file not found")
    name = item.file_name or "evidence"
    return Response(
        content=item.file_data,
        media_type=item.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/disputes/{dispute_id}/evidence/{evidence_id}/file")
def download_file(
    dispute_id: uuid.UUID, evidence_id: uuid.UUID, ctx: CurrentUser, db: DbDep
) -> Response:
    try:
        item = svc.load_file(
            db, dispute_id=dispute_id, evidence_id=evidence_id, user_id=ctx.user_id
        )
    except svc.DisputeNotVisibleError as exc:
        raise ApiError(404, "not_found", "file not found") from exc
    return file_response(item)
