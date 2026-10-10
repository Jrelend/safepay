"""Beta v0.1 release safety (regression tests).

* Automatic release is DISABLED by default; an expired inspection window alone
  never releases escrow (worker, system role, or API view).
* Only the buyer's confirmation or an admin decision releases funds.
* An open dispute blocks release; release and refund are mutually exclusive.
* Automatic release can still be enabled explicitly by the owner (future).
"""

import threading
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.transactions import atomic
from app.domain.deal_states import Actor, DealAction, DealStatus
from app.services import deal_transitions as dt
from app.services.deals import view_deal
from app.worker import run_once
from tests.integration.scenario import Scenario, act, advance_to_funded, backdate, new_deal


def _status(engine: Engine, sc: Scenario) -> str:
    with engine.connect() as conn:
        return str(
            conn.execute(text("SELECT status FROM deals WHERE id = :d"), {"d": sc.deal_id}).scalar()
        )


def _escrow(engine: Engine, sc: Scenario) -> int:
    """Escrow liability balance (credits minus debits) for the deal."""
    with engine.connect() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT coalesce(sum(CASE e.direction WHEN 'CREDIT' THEN e.amount_mnt "
                    "ELSE -e.amount_mnt END), 0) FROM ledger_entries e "
                    "JOIN ledger_accounts a ON a.id = e.account_id "
                    "WHERE a.purpose = 'DEAL_ESCROW' AND a.deal_id = :d"
                ),
                {"d": sc.deal_id},
            ).scalar_one()
        )


def _settlements(engine: Engine, sc: Scenario) -> list[str]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT kind FROM ledger_transactions WHERE deal_id = :d "
                    "AND kind IN ('ESCROW_RELEASE', 'ESCROW_REFUND')"
                ),
                {"d": sc.deal_id},
            ).scalars()
        )


def delivered(app_engine: Engine, *, days_ago: int = 0) -> Scenario:
    sc = new_deal(app_engine)
    advance_to_funded(app_engine, sc)
    act(app_engine, sc, DealAction.MARK_DELIVERED, Actor.SELLER)
    if days_ago:
        backdate(sc.deal_id, days_ago)
    return sc


@pytest.fixture
def auto_release_enabled(engine: Engine) -> Iterator[None]:
    """Temporarily enable the policy as the OWNER (the only role allowed to)."""
    with engine.begin() as conn:
        conn.execute(text("UPDATE platform_policy SET auto_release_enabled = true WHERE id"))
    try:
        yield
    finally:
        with engine.begin() as conn:
            conn.execute(text("UPDATE platform_policy SET auto_release_enabled = false WHERE id"))


# --- disabled by default -------------------------------------------------------------


def test_policy_defaults_to_disabled(app_engine: Engine) -> None:
    with app_engine.connect() as conn:
        rows = conn.execute(text("SELECT id, auto_release_enabled FROM platform_policy")).all()
    assert rows == [(True, False)]


def test_expired_inspection_window_does_not_release_via_system_role(
    app_engine: Engine, system_engine: Engine
) -> None:
    sc = delivered(app_engine, days_ago=30)  # far past the 3-day window
    with Session(system_engine) as s, atomic(s), pytest.raises(dt.AutoReleaseDisabledError):
        dt.system_transition(s, deal_id=sc.deal_id, action=DealAction.AUTO_RELEASE)
    assert _status(app_engine, sc) == DealStatus.DELIVERED
    assert _escrow(app_engine, sc) == sc.amount_mnt
    assert _settlements(app_engine, sc) == []


@pytest.mark.parametrize("worker_flag", [False, True])
def test_worker_never_releases_when_policy_disabled(
    app_engine: Engine, system_engine: Engine, worker_flag: bool
) -> None:
    """Default worker skips release; even a misconfigured worker is refused by the DB."""
    sc = delivered(app_engine, days_ago=30)
    result = run_once(system_engine, auto_release=worker_flag)
    assert sc.deal_id not in result.released
    assert _status(app_engine, sc) == DealStatus.DELIVERED
    assert _escrow(app_engine, sc) == sc.amount_mnt


def test_api_view_promises_no_automatic_release(app_engine: Engine) -> None:
    sc = delivered(app_engine, days_ago=30)
    with Session(app_engine) as s:
        view = view_deal(s, deal_id=sc.deal_id, user_id=sc.buyer_id)
    assert view.inspection_ends_at is not None
    assert view.auto_release_at is None
    assert DealAction.AUTO_RELEASE not in view.actions


@pytest.mark.parametrize("role", ["app", "system", "admin"])
def test_no_runtime_role_can_enable_auto_release(
    role: str, app_engine: Engine, system_engine: Engine, admin_api_engine: Engine
) -> None:
    eng = {"app": app_engine, "system": system_engine, "admin": admin_api_engine}[role]
    for sql in (
        "UPDATE platform_policy SET auto_release_enabled = true",
        "DELETE FROM platform_policy",
        "INSERT INTO platform_policy (id, auto_release_enabled) VALUES (true, true)",
    ):
        with eng.connect() as conn, pytest.raises(DBAPIError, match="permission denied"):
            conn.execute(text(sql))


def test_policy_row_cannot_be_deleted_or_duplicated_even_by_owner(engine: Engine) -> None:
    with engine.connect() as conn, pytest.raises(DBAPIError, match="cannot be deleted"):
        conn.execute(text("DELETE FROM platform_policy"))
    with engine.connect() as conn, pytest.raises(DBAPIError):
        conn.execute(text("INSERT INTO platform_policy (id) VALUES (false)"))


# --- what CAN release ----------------------------------------------------------------


def test_buyer_confirmation_releases(app_engine: Engine) -> None:
    sc = delivered(app_engine, days_ago=30)
    act(app_engine, sc, DealAction.CONFIRM_RECEIPT, Actor.BUYER)
    assert _status(app_engine, sc) == DealStatus.COMPLETED
    assert _escrow(app_engine, sc) == 0
    assert _settlements(app_engine, sc) == ["ESCROW_RELEASE"]


def test_seller_cannot_release_to_themselves(app_engine: Engine) -> None:
    sc = delivered(app_engine, days_ago=30)
    with pytest.raises(dt.DealTransitionError):
        act(app_engine, sc, DealAction.CONFIRM_RECEIPT, Actor.SELLER)
    assert _escrow(app_engine, sc) == sc.amount_mnt


def test_admin_decision_releases_after_buyer_goes_silent(app_engine: Engine) -> None:
    """Scenario H/I: buyer never confirms -> seller escalates -> admin releases."""
    sc = delivered(app_engine, days_ago=30)
    act(app_engine, sc, DealAction.OPEN_DISPUTE, Actor.SELLER, note="Buyer does not respond.")
    act(app_engine, sc, DealAction.RESOLVE_RELEASE, Actor.ADMIN)
    assert _status(app_engine, sc) == DealStatus.COMPLETED
    assert _settlements(app_engine, sc) == ["ESCROW_RELEASE"]


# --- disputes block release; release and refund are exclusive -------------------------


def test_open_dispute_blocks_every_release_path(
    app_engine: Engine, system_engine: Engine, auto_release_enabled: None
) -> None:
    sc = delivered(app_engine, days_ago=30)
    act(app_engine, sc, DealAction.OPEN_DISPUTE, Actor.BUYER)
    with pytest.raises(dt.DealTransitionError):
        act(app_engine, sc, DealAction.CONFIRM_RECEIPT, Actor.BUYER)
    with pytest.raises(dt.DealTransitionError):
        act(app_engine, sc, DealAction.REFUND, Actor.SELLER)
    # Even with the policy ON, a disputed deal cannot be auto-released.
    with Session(system_engine) as s, atomic(s), pytest.raises(dt.NotYetEligibleError):
        dt.system_transition(s, deal_id=sc.deal_id, action=DealAction.AUTO_RELEASE)
    assert sc.deal_id not in run_once(system_engine, auto_release=True).released
    assert _status(app_engine, sc) == DealStatus.DISPUTED
    assert _escrow(app_engine, sc) == sc.amount_mnt


def test_dispute_opened_before_delivery_blocks_release(app_engine: Engine) -> None:
    """Scenario B: buyer disputes while FUNDED, before any confirmation."""
    sc = new_deal(app_engine)
    advance_to_funded(app_engine, sc)
    act(app_engine, sc, DealAction.OPEN_DISPUTE, Actor.BUYER)
    for action, actor in (
        (DealAction.MARK_DELIVERED, Actor.SELLER),
        (DealAction.CONFIRM_RECEIPT, Actor.BUYER),
    ):
        with pytest.raises(dt.DealTransitionError):
            act(app_engine, sc, action, actor)
    assert _escrow(app_engine, sc) == sc.amount_mnt


@pytest.mark.parametrize(
    ("first", "then"),
    [
        ((DealAction.CONFIRM_RECEIPT, Actor.BUYER), (DealAction.REFUND, Actor.SELLER)),
        ((DealAction.REFUND, Actor.SELLER), (DealAction.CONFIRM_RECEIPT, Actor.BUYER)),
        ((DealAction.CONFIRM_RECEIPT, Actor.BUYER), (DealAction.REFUND, Actor.ADMIN)),
    ],
)
def test_release_and_refund_are_mutually_exclusive(
    app_engine: Engine, first: tuple[DealAction, Actor], then: tuple[DealAction, Actor]
) -> None:
    sc = delivered(app_engine)
    act(app_engine, sc, *first)
    with pytest.raises(dt.DealTransitionError):
        act(app_engine, sc, *then)
    assert len(_settlements(app_engine, sc)) == 1
    assert _escrow(app_engine, sc) == 0


def _race_confirm_vs_refund(app_engine: Engine, sc: Scenario) -> dict[str, Any]:
    barrier = threading.Barrier(2)
    out: dict[str, Any] = {}

    def run(name: str, action: DealAction, actor: Actor) -> None:
        barrier.wait()
        try:
            out[name] = act(app_engine, sc, action, actor)
        except dt.DealTransitionError as exc:
            out[name] = exc

    threads = [
        threading.Thread(target=run, args=("confirm", DealAction.CONFIRM_RECEIPT, Actor.BUYER)),
        threading.Thread(target=run, args=("refund", DealAction.REFUND, Actor.SELLER)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return out


def test_concurrent_confirm_and_refund_settle_exactly_once(app_engine: Engine) -> None:
    """Scenario E: buyer confirms while the seller refunds, at the same instant."""
    for _ in range(5):
        sc = delivered(app_engine)
        out = _race_confirm_vs_refund(app_engine, sc)
        winners = [k for k, v in out.items() if not isinstance(v, Exception)]
        assert len(winners) == 1, out
        assert len(_settlements(app_engine, sc)) == 1
        assert _escrow(app_engine, sc) == 0


def test_failed_release_is_atomic(app_engine: Engine) -> None:
    """A release that fails mid-transaction leaves no partial ledger or status change."""
    sc = delivered(app_engine)
    with Session(app_engine) as s, pytest.raises(RuntimeError), atomic(s):
        dt.transition_deal(
            s,
            deal_id=sc.deal_id,
            action=DealAction.CONFIRM_RECEIPT,
            actor_user_id=sc.buyer_id,
            idempotency_key=f"atomic-{uuid.uuid4()}",
        )
        raise RuntimeError("crash after the release, before commit")
    assert _status(app_engine, sc) == DealStatus.DELIVERED
    assert _escrow(app_engine, sc) == sc.amount_mnt
    assert _settlements(app_engine, sc) == []


# --- explicit future opt-in still works ----------------------------------------------


def test_explicitly_enabled_auto_release_respects_the_window(
    app_engine: Engine, system_engine: Engine, auto_release_enabled: None
) -> None:
    early = delivered(app_engine, days_ago=1)
    due = delivered(app_engine, days_ago=4)
    result = run_once(system_engine, auto_release=True)
    assert due.deal_id in result.released and early.deal_id not in result.released
    assert _status(app_engine, due) == DealStatus.COMPLETED
    assert _status(app_engine, early) == DealStatus.DELIVERED
    with Session(app_engine) as s:
        assert view_deal(s, deal_id=early.deal_id, user_id=early.buyer_id).auto_release_at
