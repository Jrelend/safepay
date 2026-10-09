"""Deal creation, drafts, invitations and read models (public API, safepay_app).

Authorization rule for every function: the caller must be a participant of the
deal; otherwise the deal "does not exist" (404), so ids cannot be probed.
"""

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import new_token, sha256_hex
from app.domain.deal_states import TERMINAL_STATES, Actor, DealAction, DealStatus, allowed_actions
from app.domain.deal_terms import DeliveryMethod, ItemType, check_terms
from app.models import (
    AuditEvent,
    Deal,
    DealParticipant,
    Dispute,
    LedgerAccount,
    LedgerEntry,
    LedgerTransaction,
    Notification,
    ParticipantRole,
    User,
)
from app.services.deal_transitions import PUBLIC_ACTIONS

_REF_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


class DealNotVisibleError(Exception):
    """Unknown deal, or the caller is not a participant (indistinguishable)."""


class InviteError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class DraftError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Terms:
    title: str
    description: str
    amount_mnt: int
    item_type: ItemType
    delivery_method: DeliveryMethod
    inspection_days: int


def _reference() -> str:
    return "SP-" + "".join(secrets.choice(_REF_ALPHABET) for _ in range(8))


def _audit(
    db: Session,
    *,
    actor: ParticipantRole,
    user_id: uuid.UUID,
    action: str,
    deal_id: uuid.UUID,
    data: dict[str, Any],
    request_id: str | None,
) -> None:
    db.add(
        AuditEvent(
            actor_type=Actor(actor.value),
            actor_user_id=user_id,
            action=action,
            entity_type="deal",
            entity_id=deal_id,
            deal_id=deal_id,
            request_id=request_id,
            data=data,
        )
    )


def create_deal(
    db: Session,
    *,
    creator_id: uuid.UUID,
    creator_role: ParticipantRole,
    terms: Terms,
    invite_email: str | None,
    request_id: str | None,
) -> tuple[Deal, str]:
    """Returns the deal and the raw invite token (shown to the creator once)."""
    check_terms(terms.item_type, terms.delivery_method)
    token = new_token()
    for _ in range(5):
        deal = Deal(
            reference=_reference(),
            title=terms.title,
            description=terms.description,
            amount_mnt=terms.amount_mnt,
            item_type=terms.item_type,
            delivery_method=terms.delivery_method,
            inspection_days=terms.inspection_days,
            created_by_id=creator_id,
            invite_token_hash=sha256_hex(token),
            invite_email=invite_email,
        )
        try:
            with db.begin_nested():
                db.add(deal)
                db.flush()
            break
        except IntegrityError:  # reference collision; retry with a new one
            continue
    else:  # pragma: no cover - 32^8 references
        raise RuntimeError("could not allocate a deal reference")
    db.add(DealParticipant(deal_id=deal.id, user_id=creator_id, role=creator_role))
    _audit(
        db,
        actor=creator_role,
        user_id=creator_id,
        action="deal.created",
        deal_id=deal.id,
        data={"amount_mnt": terms.amount_mnt, "title": terms.title},
        request_id=request_id,
    )
    db.flush()
    return deal, token


def participant_role(db: Session, deal_id: uuid.UUID, user_id: uuid.UUID) -> ParticipantRole:
    role = db.scalar(
        select(DealParticipant.role).where(
            DealParticipant.deal_id == deal_id, DealParticipant.user_id == user_id
        )
    )
    if role is None:
        raise DealNotVisibleError
    return role


def update_draft(
    db: Session,
    *,
    deal_id: uuid.UUID,
    user_id: uuid.UUID,
    expected_version: int,
    changes: dict[str, Any],
    request_id: str | None,
) -> Deal:
    role = participant_role(db, deal_id, user_id)
    deal = db.scalars(select(Deal).where(Deal.id == deal_id).with_for_update()).one()
    if deal.created_by_id != user_id:
        raise DraftError("not_creator")
    if deal.status is not DealStatus.DRAFT:
        raise DraftError("not_draft")
    if deal.version != expected_version:
        raise DraftError("stale_version")
    item_type = changes.get("item_type", deal.item_type)
    delivery = changes.get("delivery_method", deal.delivery_method)
    check_terms(ItemType(item_type), DeliveryMethod(delivery))
    for field, value in changes.items():
        setattr(deal, field, value)
    _audit(
        db,
        actor=role,
        user_id=user_id,
        action="deal.updated",
        deal_id=deal_id,
        data={"fields": sorted(changes)},
        request_id=request_id,
    )
    db.flush()  # bumps version (optimistic lock) and fires the DB guards
    return deal


def regenerate_invite(
    db: Session, *, deal_id: uuid.UUID, user_id: uuid.UUID, invite_email: str | None
) -> str:
    participant_role(db, deal_id, user_id)
    deal = db.scalars(select(Deal).where(Deal.id == deal_id).with_for_update()).one()
    if deal.created_by_id != user_id:
        raise DraftError("not_creator")
    if deal.status is not DealStatus.DRAFT:
        raise DraftError("not_draft")
    token = new_token()
    deal.invite_token_hash = sha256_hex(token)
    deal.invite_email = invite_email
    db.flush()
    return token


def _deal_for_invite(db: Session, token: str, *, lock: bool) -> Deal:
    stmt = select(Deal).where(Deal.invite_token_hash == sha256_hex(token))
    deal = db.scalars(stmt.with_for_update() if lock else stmt).one_or_none()
    if deal is None or deal.status is not DealStatus.DRAFT:
        raise InviteError("invite_not_found")
    return deal


@dataclass(frozen=True, slots=True)
class InvitePreview:
    deal: Deal
    creator_name: str
    offered_role: ParticipantRole


def preview_invite(db: Session, *, token: str, user_id: uuid.UUID, email: str) -> InvitePreview:
    deal = _deal_for_invite(db, token, lock=False)
    participants = db.scalars(
        select(DealParticipant).where(DealParticipant.deal_id == deal.id)
    ).all()
    if any(p.user_id == user_id for p in participants):
        raise InviteError("self_deal" if deal.created_by_id == user_id else "already_joined")
    if len(participants) >= 2:
        raise InviteError("invite_used")
    if deal.invite_email and deal.invite_email != email:
        raise InviteError("invite_restricted")
    creator_role = participants[0].role
    offered = (
        ParticipantRole.SELLER if creator_role is ParticipantRole.BUYER else ParticipantRole.BUYER
    )
    creator = db.get_one(User, deal.created_by_id)
    return InvitePreview(deal, creator.display_name, offered)


def join_deal(
    db: Session, *, token: str, user_id: uuid.UUID, email: str, request_id: str | None
) -> Deal:
    deal = _deal_for_invite(db, token, lock=True)
    preview = preview_invite(db, token=token, user_id=user_id, email=email)
    db.add(DealParticipant(deal_id=deal.id, user_id=user_id, role=preview.offered_role))
    db.add(
        Notification(
            user_id=deal.created_by_id,
            kind="deal.joined",
            deal_id=deal.id,
            data={"title": deal.title, "reference": deal.reference},
        )
    )
    _audit(
        db,
        actor=preview.offered_role,
        user_id=user_id,
        action="deal.joined",
        deal_id=deal.id,
        data={},
        request_id=request_id,
    )
    try:
        db.flush()
    except IntegrityError as exc:  # raced with another joiner
        raise InviteError("invite_used") from exc
    return deal


# ----------------------------------------------------------------- read models


@dataclass(frozen=True, slots=True)
class DealView:
    deal: Deal
    my_role: ParticipantRole
    created_by_me: bool
    counterparty_name: str | None
    counterparty_phone: str | None
    my_accepted: bool
    counterparty_accepted: bool
    dispute_id: uuid.UUID | None
    actions: list[DealAction]
    auto_release_at: datetime | None


def _actions(
    deal: Deal, role: ParticipantRole, created_by_me: bool, has_counterparty: bool
) -> list[DealAction]:
    result = []
    for action in allowed_actions(deal.status, Actor(role.value)):
        if action not in PUBLIC_ACTIONS:
            continue
        if action is DealAction.SUBMIT and (not created_by_me or not has_counterparty):
            continue
        if action in (DealAction.ACCEPT, DealAction.DECLINE) and created_by_me:
            continue
        result.append(action)
    return result


def view_deal(db: Session, *, deal_id: uuid.UUID, user_id: uuid.UUID) -> DealView:
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise DealNotVisibleError
    parts = db.execute(
        select(DealParticipant, User)
        .join(User, User.id == DealParticipant.user_id)
        .where(DealParticipant.deal_id == deal_id)
    ).all()
    mine = next((p for p, _ in parts if p.user_id == user_id), None)
    if mine is None:
        raise DealNotVisibleError
    other = next(((p, u) for p, u in parts if p.user_id != user_id), None)
    created_by_me = deal.created_by_id == user_id
    dispute_id = db.scalar(select(Dispute.id).where(Dispute.deal_id == deal_id))
    auto_release = (
        deal.status_changed_at + timedelta(days=deal.inspection_days)
        if deal.status is DealStatus.DELIVERED
        else None
    )
    return DealView(
        deal=deal,
        my_role=mine.role,
        created_by_me=created_by_me,
        counterparty_name=other[1].display_name if other else None,
        counterparty_phone=(
            other[1].phone_e164
            if other and deal.status not in (DealStatus.DRAFT, DealStatus.PENDING_ACCEPTANCE)
            else None
        ),
        my_accepted=mine.accepted_at is not None,
        counterparty_accepted=bool(other and other[0].accepted_at is not None),
        dispute_id=dispute_id,
        actions=_actions(deal, mine.role, created_by_me, other is not None),
        auto_release_at=auto_release,
    )


def list_deals(
    db: Session, *, user_id: uuid.UUID, scope: str, limit: int = 50
) -> list[tuple[Deal, ParticipantRole]]:
    stmt = (
        select(Deal, DealParticipant.role)
        .join(DealParticipant, DealParticipant.deal_id == Deal.id)
        .where(DealParticipant.user_id == user_id)
        .order_by(Deal.updated_at.desc())
        .limit(limit)
    )
    if scope == "active":
        stmt = stmt.where(Deal.status.not_in(TERMINAL_STATES))
    elif scope == "closed":
        stmt = stmt.where(Deal.status.in_(TERMINAL_STATES))
    return [(d, r) for d, r in db.execute(stmt).all()]


def timeline(db: Session, *, deal_id: uuid.UUID, user_id: uuid.UUID) -> list[AuditEvent]:
    participant_role(db, deal_id, user_id)
    return list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.deal_id == deal_id)
            .order_by(AuditEvent.occurred_at, AuditEvent.id)
        )
    )


def escrow_postings(
    db: Session, *, deal_id: uuid.UUID, user_id: uuid.UUID
) -> list[LedgerTransaction]:
    participant_role(db, deal_id, user_id)
    return list(
        db.scalars(
            select(LedgerTransaction)
            .where(LedgerTransaction.deal_id == deal_id)
            .order_by(LedgerTransaction.created_at)
        )
    )


def wallet(
    db: Session, *, user_id: uuid.UUID
) -> tuple[int, list[tuple[LedgerEntry, LedgerTransaction]]]:
    account = db.scalar(
        select(LedgerAccount).where(
            LedgerAccount.owner_user_id == user_id, LedgerAccount.purpose == "USER_WALLET"
        )
    )
    if account is None:
        return 0, []
    rows = db.execute(
        select(LedgerEntry, LedgerTransaction)
        .join(LedgerTransaction, LedgerTransaction.id == LedgerEntry.transaction_id)
        .where(LedgerEntry.account_id == account.id)
        .order_by(LedgerEntry.created_at.desc())
        .limit(100)
    ).all()
    balance = db.scalar(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (LedgerEntry.direction == "CREDIT", LedgerEntry.amount_mnt),
                        else_=-LedgerEntry.amount_mnt,
                    )
                ),
                0,
            )
        ).where(LedgerEntry.account_id == account.id)
    )
    return int(balance or 0), [(e, t) for e, t in rows]


def unread_count(db: Session, *, user_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        )
        or 0
    )
