"""Deals: create, draft edits, invitations, actions, history (public API).

Identity always comes from the session (``VerifiedUser``/``CurrentUser``).
Money-moving actions require an ``Idempotency-Key`` header.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth_context import CurrentUser, VerifiedUser, client_ip
from app.api.deps import SettingsDep
from app.api.errors import ApiError
from app.api.routes_auth import limit
from app.api.schemas import DealOut, DealSummaryOut, PostingOut, TimelineEventOut
from app.db.session import get_db
from app.db.transactions import atomic
from app.domain.deal_states import DealAction
from app.domain.deal_terms import (
    DEFAULT_INSPECTION_DAYS,
    MAX_AMOUNT_MNT,
    MAX_INSPECTION_DAYS,
    MIN_AMOUNT_MNT,
    MIN_INSPECTION_DAYS,
    DeliveryMethod,
    IncompatibleTermsError,
    ItemType,
)
from app.models import LedgerEntry, ParticipantRole
from app.services import deal_transitions as dt
from app.services import deals as svc
from app.services import rate_limit as rl
from app.services.accounts import InvalidEmailError, normalize_email
from app.services.idempotency import IdempotencyKeyReusedError, InvalidIdempotencyKeyError

router = APIRouter(tags=["deals"])
DbDep = Annotated[Session, Depends(get_db)]

Amount = Annotated[int, Field(ge=MIN_AMOUNT_MNT, le=MAX_AMOUNT_MNT, strict=False)]
InspectionDays = Annotated[int, Field(ge=MIN_INSPECTION_DAYS, le=MAX_INSPECTION_DAYS)]


class CreateDealIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=5000)
    amount_mnt: Amount
    item_type: ItemType
    delivery_method: DeliveryMethod
    inspection_days: InspectionDays = DEFAULT_INSPECTION_DAYS
    my_role: ParticipantRole
    counterparty_email: str | None = Field(default=None, max_length=254)


class UpdateDraftIn(BaseModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    amount_mnt: Amount | None = None
    item_type: ItemType | None = None
    delivery_method: DeliveryMethod | None = None
    inspection_days: InspectionDays | None = None


class InviteIn(BaseModel):
    counterparty_email: str | None = Field(default=None, max_length=254)


class ActionIn(BaseModel):
    action: DealAction
    expected_version: int | None = Field(default=None, ge=1)
    note: str | None = Field(default=None, max_length=5000)


class CreatedDealOut(BaseModel):
    deal: DealOut
    invite_url: str


class InviteOut(BaseModel):
    invite_url: str


class InvitePreviewOut(BaseModel):
    reference: str
    title: str
    description: str
    amount_mnt: str
    item_type: ItemType
    delivery_method: DeliveryMethod
    inspection_days: int
    creator_name: str
    offered_role: ParticipantRole


class ActionOut(BaseModel):
    deal: DealOut
    replayed: bool
    ledger_transaction_id: uuid.UUID | None


def _invite_email(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return normalize_email(raw)
    except InvalidEmailError as exc:
        raise ApiError(422, "invalid_email", "counterparty email is not valid") from exc


def _deal_out(view: svc.DealView) -> DealOut:
    d = view.deal
    return DealOut(
        id=d.id,
        reference=d.reference,
        title=d.title,
        description=d.description,
        amount_mnt=str(d.amount_mnt),
        currency=d.currency,
        status=d.status,
        version=d.version,
        item_type=d.item_type,
        delivery_method=d.delivery_method,
        inspection_days=d.inspection_days,
        my_role=view.my_role,
        created_by_me=view.created_by_me,
        counterparty_name=view.counterparty_name,
        counterparty_phone=view.counterparty_phone,
        my_accepted=view.my_accepted,
        counterparty_accepted=view.counterparty_accepted,
        dispute_id=view.dispute_id,
        actions=view.actions,
        inspection_ends_at=view.inspection_ends_at,
        auto_release_at=view.auto_release_at,
        status_changed_at=d.status_changed_at,
        created_at=d.created_at,
    )


def _view(db: Session, deal_id: uuid.UUID, user_id: uuid.UUID) -> DealOut:
    try:
        return _deal_out(svc.view_deal(db, deal_id=deal_id, user_id=user_id))
    except svc.DealNotVisibleError as exc:
        raise ApiError(404, "not_found", "deal not found") from exc


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.post("/deals", response_model=CreatedDealOut, status_code=201)
def create_deal(
    body: CreateDealIn, ctx: VerifiedUser, request: Request, db: DbDep, settings: SettingsDep
) -> CreatedDealOut:
    limit(request, rl.MUTATION_PER_USER, str(ctx.user_id))
    invite_email = _invite_email(body.counterparty_email)
    if invite_email == ctx.email:
        raise ApiError(422, "self_deal", "you cannot make a deal with yourself")
    try:
        with atomic(db):
            deal, token = svc.create_deal(
                db,
                creator_id=ctx.user_id,
                creator_role=body.my_role,
                terms=svc.Terms(
                    title=body.title.strip(),
                    description=body.description.strip(),
                    amount_mnt=body.amount_mnt,
                    item_type=body.item_type,
                    delivery_method=body.delivery_method,
                    inspection_days=body.inspection_days,
                ),
                invite_email=invite_email,
                request_id=_request_id(request),
            )
    except IncompatibleTermsError as exc:
        raise ApiError(422, "incompatible_terms", str(exc)) from exc
    return CreatedDealOut(
        deal=_view(db, deal.id, ctx.user_id),
        invite_url=f"{settings.public_web_url}/invite/{token}",
    )


@router.get("/deals", response_model=list[DealSummaryOut])
def list_deals(
    ctx: CurrentUser, db: DbDep, scope: Literal["active", "closed", "all"] = "all"
) -> list[DealSummaryOut]:
    return [
        DealSummaryOut(
            id=d.id,
            reference=d.reference,
            title=d.title,
            amount_mnt=str(d.amount_mnt),
            status=d.status,
            my_role=role,
            updated_at=d.updated_at,
        )
        for d, role in svc.list_deals(db, user_id=ctx.user_id, scope=scope)
    ]


@router.get("/deals/{deal_id}", response_model=DealOut)
def get_deal(deal_id: uuid.UUID, ctx: CurrentUser, db: DbDep) -> DealOut:
    return _view(db, deal_id, ctx.user_id)


@router.patch("/deals/{deal_id}", response_model=DealOut)
def update_draft(
    deal_id: uuid.UUID, body: UpdateDraftIn, ctx: VerifiedUser, request: Request, db: DbDep
) -> DealOut:
    limit(request, rl.MUTATION_PER_USER, str(ctx.user_id))
    changes = body.model_dump(exclude_none=True, exclude={"expected_version"})
    if not changes:
        raise ApiError(422, "no_changes", "nothing to update")
    for key in ("title", "description"):
        if key in changes:
            changes[key] = changes[key].strip()
    try:
        with atomic(db):
            svc.update_draft(
                db,
                deal_id=deal_id,
                user_id=ctx.user_id,
                expected_version=body.expected_version,
                changes=changes,
                request_id=_request_id(request),
            )
    except svc.DealNotVisibleError as exc:
        raise ApiError(404, "not_found", "deal not found") from exc
    except svc.DraftError as exc:
        status = 409 if exc.code in ("stale_version", "not_draft") else 403
        raise ApiError(status, exc.code, "deal cannot be edited") from exc
    except IncompatibleTermsError as exc:
        raise ApiError(422, "incompatible_terms", str(exc)) from exc
    return _view(db, deal_id, ctx.user_id)


@router.post("/deals/{deal_id}/invite", response_model=InviteOut)
def regenerate_invite(
    deal_id: uuid.UUID, body: InviteIn, ctx: VerifiedUser, db: DbDep, settings: SettingsDep
) -> InviteOut:
    invite_email = _invite_email(body.counterparty_email)
    if invite_email == ctx.email:
        raise ApiError(422, "self_deal", "you cannot make a deal with yourself")
    try:
        with atomic(db):
            token = svc.regenerate_invite(
                db, deal_id=deal_id, user_id=ctx.user_id, invite_email=invite_email
            )
    except svc.DealNotVisibleError as exc:
        raise ApiError(404, "not_found", "deal not found") from exc
    except svc.DraftError as exc:
        raise ApiError(409 if exc.code == "not_draft" else 403, exc.code, "cannot invite") from exc
    return InviteOut(invite_url=f"{settings.public_web_url}/invite/{token}")


_INVITE_STATUS = {
    "invite_not_found": 404,
    "invite_used": 409,
    "already_joined": 409,
    "self_deal": 422,
    "invite_restricted": 403,
}


@router.get("/invites/{token}", response_model=InvitePreviewOut)
def preview_invite(
    token: str, ctx: VerifiedUser, request: Request, db: DbDep, settings: SettingsDep
) -> InvitePreviewOut:
    limit(request, rl.TOKEN_ATTEMPT_PER_IP, client_ip(request, settings))
    try:
        p = svc.preview_invite(db, token=token, user_id=ctx.user_id, email=ctx.email)
    except svc.InviteError as exc:
        raise ApiError(_INVITE_STATUS[exc.code], exc.code, "invitation unavailable") from exc
    return InvitePreviewOut(
        reference=p.deal.reference,
        title=p.deal.title,
        description=p.deal.description,
        amount_mnt=str(p.deal.amount_mnt),
        item_type=p.deal.item_type,
        delivery_method=p.deal.delivery_method,
        inspection_days=p.deal.inspection_days,
        creator_name=p.creator_name,
        offered_role=p.offered_role,
    )


@router.post("/invites/{token}/join", response_model=DealOut)
def join(
    token: str, ctx: VerifiedUser, request: Request, db: DbDep, settings: SettingsDep
) -> DealOut:
    limit(request, rl.TOKEN_ATTEMPT_PER_IP, client_ip(request, settings))
    try:
        with atomic(db):
            deal = svc.join_deal(
                db,
                token=token,
                user_id=ctx.user_id,
                email=ctx.email,
                request_id=_request_id(request),
            )
    except svc.InviteError as exc:
        raise ApiError(_INVITE_STATUS[exc.code], exc.code, "invitation unavailable") from exc
    return _view(db, deal.id, ctx.user_id)


_TRANSITION_ERRORS: dict[type[dt.DealTransitionError], tuple[int, str]] = {
    dt.DealNotFoundError: (404, "not_found"),
    dt.StaleDealVersionError: (409, "stale_version"),
    dt.TransitionNotAllowedError: (409, "action_not_allowed"),
    dt.ParticipantMismatchError: (409, "participants_incomplete"),
    dt.EscrowInvariantError: (409, "escrow_invariant"),
    dt.UserNotEligibleError: (403, "email_not_verified"),
    dt.ReasonRequiredError: (422, "reason_required"),
}


@router.post("/deals/{deal_id}/actions", response_model=ActionOut)
def act(
    deal_id: uuid.UUID,
    body: ActionIn,
    ctx: VerifiedUser,
    request: Request,
    db: DbDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ActionOut:
    if not idempotency_key:
        raise ApiError(400, "idempotency_key_required", "send an Idempotency-Key header")
    limit(request, rl.MUTATION_PER_USER, str(ctx.user_id))
    try:
        svc.participant_role(db, deal_id, ctx.user_id)  # 404 for non-participants (no probing)
        db.rollback()
        with atomic(db):
            result = dt.transition_deal(
                db,
                deal_id=deal_id,
                action=body.action,
                actor_user_id=ctx.user_id,
                idempotency_key=idempotency_key,
                expected_version=body.expected_version,
                note=body.note,
                request_id=_request_id(request),
            )
    except svc.DealNotVisibleError as exc:
        raise ApiError(404, "not_found", "deal not found") from exc
    except InvalidIdempotencyKeyError as exc:
        raise ApiError(400, "invalid_idempotency_key", str(exc)) from exc
    except IdempotencyKeyReusedError as exc:
        raise ApiError(409, "idempotency_key_reused", str(exc)) from exc
    except dt.DealTransitionError as exc:
        status, code = _TRANSITION_ERRORS.get(type(exc), (409, "action_not_allowed"))
        raise ApiError(status, code, "action not possible in the current state") from exc
    return ActionOut(
        deal=_view(db, deal_id, ctx.user_id),
        replayed=result.replayed,
        ledger_transaction_id=result.ledger_transaction_id,
    )


@router.get("/deals/{deal_id}/timeline", response_model=list[TimelineEventOut])
def deal_timeline(deal_id: uuid.UUID, ctx: CurrentUser, db: DbDep) -> list[TimelineEventOut]:
    try:
        events = svc.timeline(db, deal_id=deal_id, user_id=ctx.user_id)
    except svc.DealNotVisibleError as exc:
        raise ApiError(404, "not_found", "deal not found") from exc
    allowed = {"action", "from", "to", "amount_mnt", "reason", "title", "fields"}
    return [
        TimelineEventOut(
            action=e.action,
            actor=e.actor_type.value,
            occurred_at=e.occurred_at,
            data={
                k: (str(v) if k == "amount_mnt" else v) for k, v in e.data.items() if k in allowed
            },
        )
        for e in events
    ]


@router.get("/deals/{deal_id}/escrow", response_model=list[PostingOut])
def deal_escrow(deal_id: uuid.UUID, ctx: CurrentUser, db: DbDep) -> list[PostingOut]:
    try:
        txs = svc.escrow_postings(db, deal_id=deal_id, user_id=ctx.user_id)
    except svc.DealNotVisibleError as exc:
        raise ApiError(404, "not_found", "deal not found") from exc
    out = []
    for tx in txs:
        amount = db.scalar(
            select(LedgerEntry.amount_mnt).where(
                LedgerEntry.transaction_id == tx.id, LedgerEntry.direction == "DEBIT"
            )
        )
        out.append(PostingOut(kind=tx.kind, amount_mnt=str(amount), created_at=tx.created_at))
    return out
