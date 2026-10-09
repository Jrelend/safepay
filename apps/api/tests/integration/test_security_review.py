"""Regression tests for weaknesses found in the Phase 1A security review.

Each test fails on the pre-review code (commit f454d5c) and passes after the fix.
"""

import threading
import uuid
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.transactions import atomic
from app.domain.deal_states import Actor, DealAction, DealStatus
from app.models import ParticipantRole
from app.services.deal_transitions import ParticipantMismatchError, TransitionNotAllowedError
from tests.integration.conftest import add_participant, make_deal, make_user
from tests.integration.scenario import Scenario, act, advance_to_funded, new_deal

# --- Finding 1: future functions were executable by PUBLIC (and so by the app) -----


def test_functions_created_later_are_not_executable_by_app(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("CREATE FUNCTION safepay_probe() RETURNS int LANGUAGE sql AS 'SELECT 1'"))
        can_execute = conn.execute(
            text("SELECT has_function_privilege('safepay_app', 'safepay_probe()', 'EXECUTE')")
        ).scalar_one()
        conn.rollback()
    assert can_execute is False


# --- Finding 2: trigger functions resolved tables via the caller's search_path -----


def test_every_safepay_function_pins_search_path(engine: Engine) -> None:
    with engine.connect() as conn:
        unpinned = (
            conn.execute(
                text(
                    """
                SELECT p.proname FROM pg_proc p
                  JOIN pg_namespace n ON n.oid = p.pronamespace
                 WHERE n.nspname = 'public' AND p.proname LIKE 'safepay\\_%'
                   AND NOT EXISTS (
                       SELECT FROM unnest(coalesce(p.proconfig, '{}')) c
                        WHERE c = 'search_path=pg_catalog, public, pg_temp')
                """
                )
            )
            .scalars()
            .all()
        )
    assert unpinned == []


def test_temp_table_cannot_shadow_transition_rules(engine: Engine) -> None:
    """A role with TEMP (here the owner) shadows deal_transitions to allow DRAFT -> FUNDED."""
    with Session(engine) as s:
        deal = make_deal(s, make_user(s))
        s.commit()
        deal_id = deal.id
    with engine.connect() as conn:
        conn.execute(text("CREATE TEMP TABLE deal_transitions (from_status text, to_status text)"))
        conn.execute(text("INSERT INTO deal_transitions VALUES ('DRAFT', 'FUNDED')"))
        with pytest.raises(DBAPIError, match="illegal deal transition DRAFT -> FUNDED"):
            conn.execute(
                text("UPDATE deals SET status = 'FUNDED', version = version + 1 WHERE id = :id"),
                {"id": deal_id},
            )


def test_temp_table_cannot_shadow_ledger_balance_check(engine: Engine) -> None:
    """The deferred balance check runs at COMMIT with the session's search_path."""
    with Session(engine) as s:
        user = make_user(s)
        deal = make_deal(s, user)
        s.commit()
        user_id, deal_id = user.id, deal.id
    with engine.connect() as conn:
        # A fake, perfectly balanced ledger_entries in pg_temp...
        conn.execute(
            text(
                "CREATE TEMP TABLE ledger_entries AS "
                "SELECT * FROM public.ledger_entries WITH NO DATA"
            )
        )
        wallet = conn.execute(
            text(
                "INSERT INTO ledger_accounts (code, account_type, purpose, owner_user_id) "
                "VALUES (:c, 'LIABILITY', 'USER_WALLET', :u) RETURNING id"
            ),
            {"c": f"WALLET:probe-{uuid.uuid4()}", "u": user_id},
        ).scalar_one()
        escrow = conn.execute(
            text(
                "INSERT INTO ledger_accounts (code, account_type, purpose, deal_id) "
                "VALUES (:c, 'LIABILITY', 'DEAL_ESCROW', :d) RETURNING id"
            ),
            {"c": f"ESCROW:probe-{uuid.uuid4()}", "d": deal_id},
        ).scalar_one()
        tx = conn.execute(
            text(
                "INSERT INTO ledger_transactions (idempotency_key, kind, description) "
                "VALUES (:k, 'TEST', '') RETURNING id"
            ),
            {"k": f"probe-{uuid.uuid4()}"},
        ).scalar_one()
        for table, direction, amount in (
            ("pg_temp.ledger_entries", "DEBIT", 100),
            ("pg_temp.ledger_entries", "CREDIT", 100),
            ("public.ledger_entries", "DEBIT", 100),  # ...but the real one is unbalanced
            ("public.ledger_entries", "CREDIT", 1),
        ):
            conn.execute(
                text(
                    f"INSERT INTO {table} (id, transaction_id, account_id, direction, amount_mnt) "  # noqa: S608
                    "VALUES (gen_random_uuid(), :tx, :acct, :dir, :amt)"
                ),
                {
                    "tx": tx,
                    "acct": wallet if direction == "DEBIT" else escrow,
                    "dir": direction,
                    "amt": amount,
                },
            )
        with pytest.raises(DBAPIError, match="unbalanced"):
            conn.commit()


# --- Finding 3: idempotency keys were global across all users -------------------


def test_idempotency_keys_are_scoped_per_user(app_engine: Engine) -> None:
    a, b = new_deal(app_engine), new_deal(app_engine)
    first = act(app_engine, a, DealAction.SUBMIT, Actor.SELLER, key="shared-client-key")
    second = act(app_engine, b, DealAction.SUBMIT, Actor.SELLER, key="shared-client-key")
    assert first.replayed is False
    assert second.replayed is False  # B's key never collides with (or reveals) A's
    assert second.deal_id == b.deal_id


# --- Finding 4: an uncompleted idempotency claim could be committed --------------


def test_uncompleted_idempotency_claim_cannot_commit(app_engine: Engine) -> None:
    with app_engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO idempotency_records (scope, key, request_hash) "
                "VALUES ('deal.transition:squatter', 'squatted', repeat('b', 64))"
            )
        )
        with pytest.raises(DBAPIError, match="claimed but not completed"):
            conn.commit()


# --- Finding 6: a deal could leave DRAFT without both parties --------------------


def test_deal_needs_buyer_and_seller_before_leaving_draft(app_engine: Engine) -> None:
    with Session(app_engine) as s, atomic(s):
        seller = make_user(s)
        deal = make_deal(s, seller)
        add_participant(s, deal, seller, ParticipantRole.SELLER)
        sc = Scenario(deal.id, uuid.uuid4(), seller.id, deal.amount_mnt)
    with pytest.raises(ParticipantMismatchError, match="needs a buyer and a seller"):
        act(app_engine, sc, DealAction.SUBMIT, Actor.SELLER)
    assert act(app_engine, sc, DealAction.CANCEL, Actor.SELLER).to_status is DealStatus.CANCELLED


# --- Low: large objects ------------------------------------------------------------


def test_app_cannot_create_large_objects(app_engine: Engine) -> None:
    with app_engine.connect() as conn, pytest.raises(DBAPIError, match="permission denied"):
        conn.execute(text("SELECT lo_create(0)"))


# --- Concurrency: release vs refund, and shared wallet creation -------------------


def _parallel(*calls: Any) -> list[Any]:
    """Run calls at the same moment; return each result or the exception raised."""
    barrier = threading.Barrier(len(calls))
    results: list[Any] = [None] * len(calls)

    def run(i: int) -> None:
        barrier.wait()
        try:
            results[i] = calls[i]()
        except Exception as exc:
            results[i] = exc

    threads = [threading.Thread(target=run, args=(i,)) for i in range(len(calls))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)
    return results


def _ledger_kinds(engine: Engine, deal_id: uuid.UUID) -> list[str]:
    with engine.connect() as conn:
        return sorted(
            conn.execute(
                text("SELECT kind FROM ledger_transactions WHERE deal_id = :d"), {"d": deal_id}
            ).scalars()
        )


@pytest.mark.parametrize("attempt", range(5))
def test_release_and_refund_race_exactly_one_wins(app_engine: Engine, attempt: int) -> None:
    sc = new_deal(app_engine)
    advance_to_funded(app_engine, sc)
    act(app_engine, sc, DealAction.MARK_DELIVERED, Actor.SELLER)
    results = _parallel(
        lambda: act(app_engine, sc, DealAction.CONFIRM_RECEIPT, Actor.BUYER),
        lambda: act(app_engine, sc, DealAction.REFUND, Actor.SELLER),
    )
    winners = [r for r in results if not isinstance(r, Exception)]
    losers = [r for r in results if isinstance(r, Exception)]
    assert len(winners) == 1
    assert len(losers) == 1
    assert isinstance(losers[0], TransitionNotAllowedError)
    kinds = _ledger_kinds(app_engine, sc.deal_id)
    assert kinds in (["ESCROW_HOLD", "ESCROW_RELEASE"], ["ESCROW_HOLD", "ESCROW_REFUND"])


@pytest.mark.parametrize("attempt", range(20))
def test_concurrent_payouts_to_one_seller_share_one_wallet(
    app_engine: Engine, attempt: int
) -> None:
    """Regression: ON CONFLICT (code) missed the one-wallet-per-owner index (~1 in 60 races)."""
    with Session(app_engine) as s, atomic(s):
        seller = make_user(s)
        scenarios = []
        for _ in range(2):
            buyer = make_user(s)
            deal = make_deal(s, buyer, amount_mnt=70_000)
            add_participant(s, deal, buyer, ParticipantRole.BUYER)
            add_participant(s, deal, seller, ParticipantRole.SELLER)
            scenarios.append(Scenario(deal.id, buyer.id, seller.id, 70_000))
    for sc in scenarios:
        advance_to_funded(app_engine, sc)
        act(app_engine, sc, DealAction.MARK_DELIVERED, Actor.SELLER)
    results = _parallel(
        *[
            (lambda sc=sc: act(app_engine, sc, DealAction.CONFIRM_RECEIPT, Actor.BUYER))
            for sc in scenarios
        ]
    )
    assert all(not isinstance(r, Exception) for r in results), results
    with app_engine.connect() as conn:
        wallets = (
            conn.execute(
                text("SELECT id FROM ledger_accounts WHERE owner_user_id = :u"),
                {"u": scenarios[0].seller_id},
            )
            .scalars()
            .all()
        )
        assert len(wallets) == 1
        credited = conn.execute(
            text(
                "SELECT COALESCE(SUM(amount_mnt), 0) FROM ledger_entries "
                "WHERE account_id = :a AND direction = 'CREDIT'"
            ),
            {"a": wallets[0]},
        ).scalar_one()
    assert credited == 140_000
