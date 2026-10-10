"""Builders for deal scenarios.

Users, deals and participants are created through the *application* role.
``act`` routes each actor through the path that actor really uses:
BUYER/SELLER -> public function (safepay_app), ADMIN -> admin functions
(safepay_admin), SYSTEM -> system function (safepay_system).
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.db.transactions import atomic
from app.domain.deal_states import Actor, DealAction
from app.models import Admin, Dispute, ParticipantRole
from app.services import deal_transitions as dt
from tests.integration.conftest import add_participant, make_deal, make_user

ENGINES: dict[str, Engine] = {}
ADMIN_REASON = "Administrative decision for testing."


@dataclass(frozen=True)
class Scenario:
    deal_id: uuid.UUID
    buyer_id: uuid.UUID
    seller_id: uuid.UUID
    amount_mnt: int
    admin_id: uuid.UUID | None = None


def make_admin(user_id: uuid.UUID) -> None:
    """Admins are granted only with the schema-owner credential (ops CLI)."""
    with Session(ENGINES["owner"]) as s, atomic(s):
        s.add(Admin(user_id=user_id, note="test"))


def new_deal(app_engine: Engine, amount_mnt: int = 250_000) -> Scenario:
    """The SELLER creates the deal (so SELLER submits and BUYER accepts)."""
    with Session(app_engine) as s, atomic(s):
        buyer, seller, admin = make_user(s), make_user(s), make_user(s)
        deal = make_deal(s, seller, amount_mnt=amount_mnt)
        add_participant(s, deal, seller, ParticipantRole.SELLER)
        add_participant(s, deal, buyer, ParticipantRole.BUYER)
        sc = Scenario(deal.id, buyer.id, seller.id, amount_mnt, admin.id)
    assert sc.admin_id is not None
    make_admin(sc.admin_id)
    return sc


def backdate(deal_id: uuid.UUID, days: int) -> None:
    """Test-only: move status_changed_at into the past (superuser, triggers bypassed)."""
    with ENGINES["superuser"].begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(
            text("UPDATE deals SET status_changed_at = status_changed_at - :d WHERE id = :id"),
            {"d": timedelta(days=days), "id": deal_id},
        )


def act(
    app_engine: Engine,
    sc: Scenario,
    action: DealAction,
    actor: Actor,
    *,
    key: str | None = None,
    user_id: uuid.UUID | None = None,
    expected_version: int | None = None,
    note: str | None = None,
) -> dt.TransitionResult:
    if actor is Actor.SYSTEM:
        with Session(ENGINES["system"]) as s, atomic(s):
            return dt.system_transition(s, deal_id=sc.deal_id, action=action)
    if actor is Actor.ADMIN:
        admin = user_id or sc.admin_id
        assert admin is not None
        with Session(ENGINES["admin"]) as s, atomic(s):
            if action in (DealAction.RESOLVE_RELEASE, DealAction.RESOLVE_REFUND):
                dispute_id = s.scalar(select(Dispute.id).where(Dispute.deal_id == sc.deal_id))
                if dispute_id is None:
                    raise dt.TransitionNotAllowedError("no dispute")
                outcome = (
                    "RELEASE_TO_SELLER"
                    if action is DealAction.RESOLVE_RELEASE
                    else "REFUND_TO_BUYER"
                )
                return dt.admin_resolve_dispute(
                    s,
                    dispute_id=dispute_id,
                    outcome=outcome,
                    admin_user_id=admin,
                    reason=note or ADMIN_REASON,
                )
            data = dt.call_db_function(
                s,
                "SELECT safepay_admin_transition_deal(:d, :a, :admin, :r, NULL)",
                {"d": sc.deal_id, "a": action.value, "admin": admin, "r": note or ADMIN_REASON},
            )
            return dt._result(data, replayed=False)
    if user_id is None:
        user_id = sc.buyer_id if actor is Actor.BUYER else sc.seller_id
    if action is DealAction.OPEN_DISPUTE and note is None:
        note = "The item never arrived as described."
    with Session(app_engine) as s, atomic(s):
        return dt.transition_deal(
            s,
            deal_id=sc.deal_id,
            action=action,
            actor_user_id=user_id,
            idempotency_key=key or f"test-{uuid.uuid4()}",
            expected_version=expected_version,
            note=note,
        )


def advance_to_awaiting_payment(app_engine: Engine, sc: Scenario) -> None:
    act(app_engine, sc, DealAction.SUBMIT, Actor.SELLER)
    act(app_engine, sc, DealAction.ACCEPT, Actor.BUYER)


def advance_to_funded(app_engine: Engine, sc: Scenario) -> dt.TransitionResult:
    advance_to_awaiting_payment(app_engine, sc)
    return act(app_engine, sc, DealAction.FUND, Actor.BUYER)
