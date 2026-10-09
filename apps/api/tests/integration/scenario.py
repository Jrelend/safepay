"""Builders for deal scenarios, created through the *application* role."""

import uuid
from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.transactions import atomic
from app.domain.deal_states import Actor, DealAction
from app.models import ParticipantRole
from app.services.deal_transitions import TransitionResult, transition_deal
from tests.integration.conftest import add_participant, make_deal, make_user


@dataclass(frozen=True)
class Scenario:
    deal_id: uuid.UUID
    buyer_id: uuid.UUID
    seller_id: uuid.UUID
    amount_mnt: int
    admin_id: uuid.UUID | None = None


def new_deal(app_engine: Engine, amount_mnt: int = 250_000) -> Scenario:
    with Session(app_engine) as s, atomic(s):
        buyer, seller, admin = make_user(s), make_user(s), make_user(s)
        deal = make_deal(s, buyer, amount_mnt=amount_mnt)
        add_participant(s, deal, buyer, ParticipantRole.BUYER)
        add_participant(s, deal, seller, ParticipantRole.SELLER)
        return Scenario(deal.id, buyer.id, seller.id, amount_mnt, admin.id)


def act(
    app_engine: Engine,
    sc: Scenario,
    action: DealAction,
    actor: Actor,
    *,
    key: str | None = None,
    user_id: uuid.UUID | None = None,
    expected_version: int | None = None,
) -> TransitionResult:
    if user_id is None:
        user_id = {Actor.BUYER: sc.buyer_id, Actor.SELLER: sc.seller_id}.get(actor)
        if actor is Actor.ADMIN:
            user_id = sc.admin_id
    with Session(app_engine) as s, atomic(s):
        return transition_deal(
            s,
            deal_id=sc.deal_id,
            action=action,
            actor=actor,
            actor_user_id=user_id,
            idempotency_key=key or f"test-{uuid.uuid4()}",
            expected_version=expected_version,
        )


def advance_to_awaiting_payment(app_engine: Engine, sc: Scenario) -> None:
    act(app_engine, sc, DealAction.SUBMIT, Actor.SELLER)
    act(app_engine, sc, DealAction.ACCEPT, Actor.BUYER)


def advance_to_funded(app_engine: Engine, sc: Scenario) -> TransitionResult:
    advance_to_awaiting_payment(app_engine, sc)
    return act(app_engine, sc, DealAction.FUND, Actor.BUYER)
