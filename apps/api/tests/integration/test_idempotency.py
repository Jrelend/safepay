"""Idempotency: replay, conflicting reuse, concurrency, and write-once records."""

import threading
import uuid
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.transactions import atomic
from app.domain.deal_states import Actor, DealAction, DealStatus
from app.models import AuditEvent, LedgerTransaction
from app.services.deal_transitions import TransitionNotAllowedError, transition_deal
from app.services.idempotency import (
    IdempotencyKeyReusedError,
    InvalidIdempotencyKeyError,
    request_fingerprint,
    run_idempotent,
)
from tests.integration.scenario import act, advance_to_awaiting_payment, new_deal


def _count(engine: Engine, model: type[Any], deal_id: uuid.UUID) -> int:
    with Session(engine) as s:
        return int(
            s.scalar(select(func.count()).select_from(model).where(model.deal_id == deal_id)) or 0
        )


def test_same_key_same_request_returns_original_result(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    advance_to_awaiting_payment(app_engine, sc)
    first = act(app_engine, sc, DealAction.FUND, Actor.BUYER, key="fund-once")
    again = act(app_engine, sc, DealAction.FUND, Actor.BUYER, key="fund-once")
    assert first.replayed is False
    assert again.replayed is True
    assert (again.ledger_transaction_id, again.audit_event_id, again.version) == (
        first.ledger_transaction_id,
        first.audit_event_id,
        first.version,
    )
    with Session(app_engine) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(LedgerTransaction)
                .where(LedgerTransaction.deal_id == sc.deal_id)
            )
            == 1
        )
        assert (
            s.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.deal_id == sc.deal_id, AuditEvent.data["action"].astext == "FUND")
            )
            == 1
        )


def test_same_key_different_request_is_rejected(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    act(app_engine, sc, DealAction.SUBMIT, Actor.SELLER, key="reused-key")
    with pytest.raises(IdempotencyKeyReusedError):
        act(app_engine, sc, DealAction.ACCEPT, Actor.BUYER, key="reused-key")
    other = new_deal(app_engine)  # same key, same action, different deal
    with pytest.raises(IdempotencyKeyReusedError):
        act(app_engine, other, DealAction.SUBMIT, Actor.SELLER, key="reused-key")


def test_failed_attempt_is_not_cached(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    with pytest.raises(TransitionNotAllowedError):
        act(app_engine, sc, DealAction.ACCEPT, Actor.BUYER, key="retry-me")
    act(app_engine, sc, DealAction.SUBMIT, Actor.SELLER)
    result = act(app_engine, sc, DealAction.ACCEPT, Actor.BUYER, key="retry-me")
    assert result.to_status is DealStatus.AWAITING_PAYMENT
    assert result.replayed is False


def _race(app_engine: Engine, sc: Any, key: str, second_actor_user: uuid.UUID) -> dict[str, Any]:
    """First request claims the key and holds its transaction open; the second must wait."""
    claimed = threading.Event()
    out: dict[str, Any] = {}

    def first() -> None:
        with Session(app_engine) as s, atomic(s):
            out["first"] = transition_deal(
                s,
                deal_id=sc.deal_id,
                action=DealAction.FUND,
                actor=Actor.BUYER,
                actor_user_id=sc.buyer_id,
                idempotency_key=key,
            )
            claimed.set()
            threading.Event().wait(0.5)

    def second() -> None:
        claimed.wait(5)
        try:
            with Session(app_engine) as s, atomic(s):
                out["second"] = transition_deal(
                    s,
                    deal_id=sc.deal_id,
                    action=DealAction.FUND,
                    actor=Actor.BUYER,
                    actor_user_id=second_actor_user,
                    idempotency_key=key,
                )
        except Exception as exc:
            out["second"] = exc

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    return out


def test_concurrent_same_key_executes_once(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    advance_to_awaiting_payment(app_engine, sc)
    out = _race(app_engine, sc, "concurrent-key", sc.buyer_id)
    assert out["first"].replayed is False
    assert out["second"].replayed is True
    assert out["second"].ledger_transaction_id == out["first"].ledger_transaction_id
    assert _count(app_engine, LedgerTransaction, sc.deal_id) == 1


def test_concurrent_same_key_different_request_is_rejected(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    advance_to_awaiting_payment(app_engine, sc)
    out = _race(app_engine, sc, "concurrent-conflict", sc.seller_id)
    assert out["first"].to_status is DealStatus.FUNDED
    assert isinstance(out["second"], IdempotencyKeyReusedError)
    assert _count(app_engine, LedgerTransaction, sc.deal_id) == 1


@pytest.mark.parametrize("key", ["", "has space", "x" * 129, "semi;colon", "ключ"])
def test_invalid_keys_rejected(app_engine: Engine, key: str) -> None:
    with Session(app_engine) as s, atomic(s), pytest.raises(InvalidIdempotencyKeyError):
        run_idempotent(s, scope="test", key=key, request={}, operation=dict)


def test_requires_open_transaction(app_engine: Engine) -> None:
    with Session(app_engine) as s, pytest.raises(RuntimeError, match="atomic"):
        run_idempotent(s, scope="test", key="k", request={}, operation=dict)


def test_fingerprint_is_order_independent() -> None:
    a = request_fingerprint({"a": 1, "b": uuid.UUID(int=1)})
    b = request_fingerprint({"b": uuid.UUID(int=1), "a": 1})
    assert a == b
    assert a != request_fingerprint({"a": 2, "b": uuid.UUID(int=1)})


def test_completed_records_are_write_once(app_engine: Engine) -> None:
    with Session(app_engine) as s, atomic(s):
        run_idempotent(
            s, scope="test", key="write-once", request={"x": 1}, operation=lambda: {"ok": 1}
        )
    with app_engine.connect() as conn, pytest.raises(DBAPIError, match="immutable"):
        conn.execute(
            text(
                "UPDATE idempotency_records SET response = '{\"ok\": 2}' "
                "WHERE scope = 'test' AND key = 'write-once'"
            )
        )
    with app_engine.connect() as conn, pytest.raises(DBAPIError, match="permission denied"):
        conn.execute(text("UPDATE idempotency_records SET request_hash = repeat('0', 64)"))


def test_records_must_be_claimed_before_completion(app_engine: Engine) -> None:
    with app_engine.connect() as conn, pytest.raises(DBAPIError, match="claimed before"):
        conn.execute(
            text(
                "INSERT INTO idempotency_records "
                "(scope, key, request_hash, response, completed_at) "
                "VALUES ('test', 'precompleted', repeat('a', 64), '{}', now())"
            )
        )
