"""Deal transitions + simulated escrow postings through the safepay_app role."""

import threading
import uuid
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.transactions import NestedTransactionError, atomic
from app.domain.deal_states import TRANSITIONS, Actor, DealAction, DealStatus
from app.domain.ledger import AccountType, EntryDirection, LedgerTransactionKind, account_balance
from app.models import (
    AuditEvent,
    Deal,
    DealTransitionRule,
    IdempotencyRecord,
    LedgerAccount,
    LedgerEntry,
    LedgerTransaction,
)
from app.services.deal_transitions import (
    DealNotFoundError,
    DealTransitionError,
    NotAdministratorError,
    ParticipantMismatchError,
    StaleDealVersionError,
    TransitionNotAllowedError,
    idempotency_scope,
    transition_deal,
)
from tests.integration.scenario import (
    Scenario,
    act,
    advance_to_awaiting_payment,
    advance_to_funded,
    backdate,
    new_deal,
)


def _balance(engine: Engine, code: str) -> int:
    with Session(engine) as s:
        account = s.scalars(select(LedgerAccount).where(LedgerAccount.code == code)).one()
        rows = s.execute(
            select(LedgerEntry.direction, LedgerEntry.amount_mnt).where(
                LedgerEntry.account_id == account.id
            )
        ).all()
        return account_balance(account.account_type, [(d, a) for d, a in rows])


def _escrow_kinds(engine: Engine, deal_id: uuid.UUID) -> list[str]:
    with Session(engine) as s:
        return sorted(
            s.scalars(
                select(LedgerTransaction.kind).where(LedgerTransaction.deal_id == deal_id)
            ).all()
        )


def _status(engine: Engine, deal_id: uuid.UUID) -> DealStatus:
    with Session(engine) as s:
        return s.get_one(Deal, deal_id).status


def test_db_transition_table_matches_domain(app_engine: Engine) -> None:
    with Session(app_engine) as s:
        rows = {
            (r.from_status, r.action): (r.to_status, frozenset(r.actors), r.ledger_effect)
            for r in s.scalars(select(DealTransitionRule))
        }
    expected = {
        (t.source, t.action): (t.target, frozenset(a.value for a in t.actors), t.ledger_effect)
        for t in TRANSITIONS
    }
    assert rows == expected


def test_happy_path_release(app_engine: Engine) -> None:
    sc = new_deal(app_engine, amount_mnt=1_250_000)
    fund = advance_to_funded(app_engine, sc)
    assert fund.to_status is DealStatus.FUNDED
    assert fund.ledger_transaction_id is not None
    assert _balance(app_engine, f"ESCROW:{sc.deal_id}") == 1_250_000

    act(app_engine, sc, DealAction.MARK_DELIVERED, Actor.SELLER)
    done = act(app_engine, sc, DealAction.CONFIRM_RECEIPT, Actor.BUYER)

    assert done.to_status is DealStatus.COMPLETED
    assert done.version == 6
    assert _balance(app_engine, f"ESCROW:{sc.deal_id}") == 0
    assert _balance(app_engine, f"WALLET:{sc.seller_id}") == 1_250_000
    assert _escrow_kinds(app_engine, sc.deal_id) == ["ESCROW_HOLD", "ESCROW_RELEASE"]
    with Session(app_engine) as s:
        audits = s.scalars(
            select(AuditEvent)
            .where(AuditEvent.deal_id == sc.deal_id)
            .order_by(AuditEvent.occurred_at)
        ).all()
    assert [a.data["action"] for a in audits] == [
        "SUBMIT",
        "ACCEPT",
        "FUND",
        "MARK_DELIVERED",
        "CONFIRM_RECEIPT",
    ]


def test_refund_by_seller_credits_buyer(app_engine: Engine) -> None:
    sc = new_deal(app_engine, amount_mnt=40_000)
    advance_to_funded(app_engine, sc)
    result = act(app_engine, sc, DealAction.REFUND, Actor.SELLER)
    assert result.to_status is DealStatus.REFUNDED
    assert _balance(app_engine, f"WALLET:{sc.buyer_id}") == 40_000
    assert _balance(app_engine, f"ESCROW:{sc.deal_id}") == 0


def test_dispute_resolved_by_admin(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    advance_to_funded(app_engine, sc)
    act(app_engine, sc, DealAction.OPEN_DISPUTE, Actor.BUYER)
    with pytest.raises(TransitionNotAllowedError):
        act(app_engine, sc, DealAction.RESOLVE_RELEASE, Actor.SELLER)
    result = act(app_engine, sc, DealAction.RESOLVE_RELEASE, Actor.ADMIN)
    assert result.to_status is DealStatus.COMPLETED
    assert _escrow_kinds(app_engine, sc.deal_id) == ["ESCROW_HOLD", "ESCROW_RELEASE"]


# --- invalid transitions ---------------------------------------------------


def test_cannot_fund_a_draft(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    with pytest.raises(TransitionNotAllowedError, match="may not FUND a deal in state DRAFT"):
        act(app_engine, sc, DealAction.FUND, Actor.BUYER)
    assert _status(app_engine, sc.deal_id) is DealStatus.DRAFT


def test_seller_cannot_fund(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    advance_to_awaiting_payment(app_engine, sc)
    with pytest.raises(TransitionNotAllowedError):
        act(app_engine, sc, DealAction.FUND, Actor.SELLER)


def test_actor_role_is_derived_not_claimed(app_engine: Engine) -> None:
    """The public path has no actor parameter: the seller cannot fund as 'buyer'."""
    sc = new_deal(app_engine)
    advance_to_awaiting_payment(app_engine, sc)
    with pytest.raises(TransitionNotAllowedError, match="SELLER may not FUND"):
        act(app_engine, sc, DealAction.FUND, Actor.BUYER, user_id=sc.seller_id)
    # A stranger is not a participant at all.
    with pytest.raises(ParticipantMismatchError):
        act(app_engine, sc, DealAction.FUND, Actor.BUYER, user_id=uuid.uuid4())
    assert _status(app_engine, sc.deal_id) is DealStatus.AWAITING_PAYMENT


def test_public_path_cannot_perform_system_actions(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    act(app_engine, sc, DealAction.SUBMIT, Actor.SELLER)
    backdate(sc.deal_id, 30)
    for user in (sc.buyer_id, sc.seller_id):
        with pytest.raises(TransitionNotAllowedError):
            act(app_engine, sc, DealAction.EXPIRE, Actor.BUYER, user_id=user)
    # The worker role can (eligibility re-checked in SQL).
    assert act(app_engine, sc, DealAction.EXPIRE, Actor.SYSTEM).to_status is DealStatus.EXPIRED


def test_unknown_deal(app_engine: Engine) -> None:
    sc = Scenario(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), 1)
    with pytest.raises(DealNotFoundError):
        act(app_engine, sc, DealAction.SUBMIT, Actor.SELLER)


def test_stale_expected_version(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    act(app_engine, sc, DealAction.SUBMIT, Actor.SELLER, expected_version=1)
    with pytest.raises(StaleDealVersionError):
        act(app_engine, sc, DealAction.ACCEPT, Actor.BUYER, expected_version=1)


def test_cannot_leave_terminal_state(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    act(app_engine, sc, DealAction.CANCEL, Actor.BUYER)
    for action in DealAction:
        for actor in Actor:
            with pytest.raises(DealTransitionError):
                act(app_engine, sc, action, actor)
    assert _status(app_engine, sc.deal_id) is DealStatus.CANCELLED


# --- no double funding / release / refund -----------------------------------


def test_no_double_funding_sequential(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    advance_to_funded(app_engine, sc)
    with pytest.raises(TransitionNotAllowedError):
        act(app_engine, sc, DealAction.FUND, Actor.BUYER)  # new idempotency key
    assert _escrow_kinds(app_engine, sc.deal_id) == ["ESCROW_HOLD"]
    assert _balance(app_engine, f"ESCROW:{sc.deal_id}") == sc.amount_mnt


def test_no_double_funding_concurrent(app_engine: Engine) -> None:
    """Two FUND requests with different keys race; the row lock lets exactly one win."""
    sc = new_deal(app_engine)
    advance_to_awaiting_payment(app_engine, sc)
    first_done = threading.Event()
    outcomes: dict[str, Any] = {}

    def first() -> None:
        with Session(app_engine) as s, atomic(s):
            outcomes["first"] = transition_deal(
                s,
                deal_id=sc.deal_id,
                action=DealAction.FUND,
                actor_user_id=sc.buyer_id,
                idempotency_key="race-a",
            )
            first_done.set()
            threading.Event().wait(0.5)  # hold the row lock, then commit

    def second() -> None:
        first_done.wait(5)
        try:
            outcomes["second"] = act(app_engine, sc, DealAction.FUND, Actor.BUYER, key="race-b")
        except TransitionNotAllowedError as exc:
            outcomes["second"] = exc

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert outcomes["first"].to_status is DealStatus.FUNDED
    assert isinstance(outcomes["second"], TransitionNotAllowedError)
    assert _escrow_kinds(app_engine, sc.deal_id) == ["ESCROW_HOLD"]
    assert _balance(app_engine, f"ESCROW:{sc.deal_id}") == sc.amount_mnt


def test_no_double_release_or_refund(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    advance_to_funded(app_engine, sc)
    act(app_engine, sc, DealAction.MARK_DELIVERED, Actor.SELLER)
    act(app_engine, sc, DealAction.CONFIRM_RECEIPT, Actor.BUYER)
    for action, actor in [
        (DealAction.CONFIRM_RECEIPT, Actor.BUYER),
        (DealAction.REFUND, Actor.SELLER),
        (DealAction.RESOLVE_REFUND, Actor.ADMIN),
    ]:
        with pytest.raises(TransitionNotAllowedError):
            act(app_engine, sc, action, actor)
    assert _escrow_kinds(app_engine, sc.deal_id) == ["ESCROW_HOLD", "ESCROW_RELEASE"]


@pytest.mark.parametrize(
    "kind", [LedgerTransactionKind.ESCROW_RELEASE, LedgerTransactionKind.ESCROW_REFUND]
)
def test_settlement_unique_even_for_schema_owner(
    app_engine: Engine, engine: Engine, kind: LedgerTransactionKind
) -> None:
    """Defence in depth: even a buggy definer function / owner cannot settle twice."""
    sc = new_deal(app_engine)
    advance_to_funded(app_engine, sc)
    act(app_engine, sc, DealAction.MARK_DELIVERED, Actor.SELLER)
    act(app_engine, sc, DealAction.CONFIRM_RECEIPT, Actor.BUYER)
    with Session(engine) as s, pytest.raises(IntegrityError, match="uq_ledger_transactions"):
        s.add(
            LedgerTransaction(
                idempotency_key=f"forged-{uuid.uuid4()}", kind=kind, deal_id=sc.deal_id
            )
        )
        s.flush()


def test_escrow_hold_unique_even_for_schema_owner(app_engine: Engine, engine: Engine) -> None:
    sc = new_deal(app_engine)
    advance_to_funded(app_engine, sc)
    with Session(engine) as s, pytest.raises(IntegrityError, match="uq_ledger_transactions"):
        s.add(
            LedgerTransaction(
                idempotency_key=f"forged-{uuid.uuid4()}",
                kind=LedgerTransactionKind.ESCROW_HOLD,
                deal_id=sc.deal_id,
            )
        )
        s.flush()


# --- atomicity / rollback ----------------------------------------------------


def test_failure_after_transition_rolls_everything_back(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    advance_to_awaiting_payment(app_engine, sc)

    class Boom(Exception):
        pass

    with Session(app_engine) as s, pytest.raises(Boom), atomic(s):
        result = transition_deal(
            s,
            deal_id=sc.deal_id,
            action=DealAction.FUND,
            actor_user_id=sc.buyer_id,
            idempotency_key="rollback-key",
        )
        assert result.to_status is DealStatus.FUNDED  # visible inside the transaction
        raise Boom  # e.g. a crash before commit

    assert _status(app_engine, sc.deal_id) is DealStatus.AWAITING_PAYMENT
    assert _escrow_kinds(app_engine, sc.deal_id) == []
    with Session(app_engine) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.deal_id == sc.deal_id, AuditEvent.data["action"].astext == "FUND")
            )
            == 0
        )
        scope = idempotency_scope(sc.buyer_id)
        assert s.get(IdempotencyRecord, (scope, "rollback-key")) is None
    # The same key can be retried after the rollback and now succeeds.
    assert act(app_engine, sc, DealAction.FUND, Actor.BUYER, key="rollback-key").replayed is False


def test_database_error_aborts_the_whole_transaction(app_engine: Engine) -> None:
    """A rejected transition after earlier writes in the same transaction undoes them."""
    sc = new_deal(app_engine)
    with Session(app_engine) as s, pytest.raises(TransitionNotAllowedError), atomic(s):
        transition_deal(
            s,
            deal_id=sc.deal_id,
            action=DealAction.SUBMIT,
            actor_user_id=sc.seller_id,
            idempotency_key=f"k-{uuid.uuid4()}",
        )
        transition_deal(  # illegal: PENDING_ACCEPTANCE cannot be funded
            s,
            deal_id=sc.deal_id,
            action=DealAction.FUND,
            actor_user_id=sc.buyer_id,
            idempotency_key=f"k-{uuid.uuid4()}",
        )
    assert _status(app_engine, sc.deal_id) is DealStatus.DRAFT


def test_atomic_refuses_nesting(app_engine: Engine) -> None:
    with Session(app_engine) as s, atomic(s), pytest.raises(NestedTransactionError), atomic(s):
        pass


def test_ledger_stays_balanced_overall(engine: Engine) -> None:
    with engine.connect() as conn:
        debit, credit = conn.execute(
            text(
                "SELECT COALESCE(SUM(amount_mnt) FILTER (WHERE direction = 'DEBIT'), 0), "
                "COALESCE(SUM(amount_mnt) FILTER (WHERE direction = 'CREDIT'), 0) "
                "FROM ledger_entries"
            )
        ).one()
    assert debit == credit


def test_entries_direction_enum_roundtrip() -> None:
    assert {d.value for d in EntryDirection} == {"DEBIT", "CREDIT"}
    assert AccountType.LIABILITY.value == "LIABILITY"


def test_admin_actions_require_an_administrator(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    advance_to_funded(app_engine, sc)
    # The buyer is not an admin; neither is a random id.
    for who in (sc.buyer_id, uuid.uuid4()):
        with pytest.raises(NotAdministratorError):
            act(app_engine, sc, DealAction.REFUND, Actor.ADMIN, user_id=who)
    assert _status(app_engine, sc.deal_id) is DealStatus.FUNDED
