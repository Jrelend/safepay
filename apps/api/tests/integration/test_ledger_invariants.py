"""Database-enforced financial invariants. These must hold even if app code is buggy."""

import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.domain.ledger import AccountPurpose, AccountType, EntryDirection, account_balance
from app.models import LedgerAccount, LedgerEntry, LedgerTransaction
from tests.integration.conftest import make_account, make_deal, make_user

D = EntryDirection.DEBIT
C = EntryDirection.CREDIT


def _escrow_setup(session: Session) -> tuple[LedgerAccount, LedgerAccount]:
    """Return (buyer wallet, deal escrow) accounts, committed."""
    buyer = make_user(session)
    deal = make_deal(session, buyer)
    wallet = make_account(session, AccountPurpose.USER_WALLET, AccountType.LIABILITY, owner=buyer)
    escrow = make_account(session, AccountPurpose.DEAL_ESCROW, AccountType.LIABILITY, deal=deal)
    session.commit()
    return wallet, escrow


def _post(
    session: Session, legs: list[tuple[LedgerAccount, EntryDirection, int]]
) -> LedgerTransaction:
    tx = LedgerTransaction(idempotency_key=f"test:{uuid.uuid4()}", kind="TEST")
    session.add(tx)
    session.flush()
    for account, direction, amount in legs:
        session.add(
            LedgerEntry(
                transaction_id=tx.id, account_id=account.id, direction=direction, amount_mnt=amount
            )
        )
    session.flush()
    return tx


def _balance(session: Session, account: LedgerAccount) -> int:
    rows = session.execute(
        select(LedgerEntry.direction, LedgerEntry.amount_mnt).where(
            LedgerEntry.account_id == account.id
        )
    ).all()
    return account_balance(account.account_type, [(r[0], r[1]) for r in rows])


def test_balanced_transaction_commits_and_balance_is_derived(session: Session) -> None:
    wallet, escrow = _escrow_setup(session)
    _post(session, [(wallet, D, 150_000), (escrow, C, 150_000)])
    session.commit()
    assert _balance(session, escrow) == 150_000
    assert _balance(session, wallet) == -150_000


def test_unbalanced_transaction_is_rejected_at_commit(session: Session) -> None:
    wallet, escrow = _escrow_setup(session)
    _post(session, [(wallet, D, 150_000), (escrow, C, 149_999)])
    with pytest.raises(DBAPIError, match="unbalanced"):
        session.commit()


def test_single_entry_transaction_is_rejected(session: Session) -> None:
    wallet, _ = _escrow_setup(session)
    _post(session, [(wallet, D, 1_000)])
    with pytest.raises(DBAPIError, match="unbalanced"):
        session.commit()


def test_transaction_without_entries_is_rejected(session: Session) -> None:
    _escrow_setup(session)
    _post(session, [])
    with pytest.raises(DBAPIError, match="unbalanced"):
        session.commit()


def test_same_account_on_both_sides_is_rejected(session: Session) -> None:
    wallet, _ = _escrow_setup(session)
    _post(session, [(wallet, D, 500), (wallet, C, 500)])
    with pytest.raises(DBAPIError, match="unbalanced"):
        session.commit()


@pytest.mark.parametrize("amount", [0, -100])
def test_non_positive_amounts_are_rejected(session: Session, amount: int) -> None:
    wallet, escrow = _escrow_setup(session)
    with pytest.raises(IntegrityError, match="amount_positive"):
        _post(session, [(wallet, D, amount), (escrow, C, amount)])


def test_entries_cannot_be_added_to_a_committed_transaction(session: Session) -> None:
    wallet, escrow = _escrow_setup(session)
    tx = _post(session, [(wallet, D, 1_000), (escrow, C, 1_000)])
    session.commit()
    session.add(LedgerEntry(transaction_id=tx.id, account_id=wallet.id, direction=D, amount_mnt=5))
    session.add(LedgerEntry(transaction_id=tx.id, account_id=escrow.id, direction=C, amount_mnt=5))
    with pytest.raises(DBAPIError, match="sealed"):
        session.flush()


def test_idempotency_key_is_unique(session: Session) -> None:
    wallet, escrow = _escrow_setup(session)
    tx = _post(session, [(wallet, D, 1_000), (escrow, C, 1_000)])
    session.commit()
    session.add(LedgerTransaction(idempotency_key=tx.idempotency_key, kind="TEST"))
    with pytest.raises(IntegrityError, match="idempotency_key"):
        session.flush()


MUTATIONS: dict[str, Callable[[uuid.UUID], str]] = {
    "update_entry": lambda _: "UPDATE ledger_entries SET amount_mnt = amount_mnt + 1",
    "delete_entry": lambda _: "DELETE FROM ledger_entries",
    "update_tx": lambda _: "UPDATE ledger_transactions SET description = 'edited'",
    "delete_tx": lambda _: "DELETE FROM ledger_transactions",
    "truncate_entries": lambda _: "TRUNCATE ledger_entries",
    "truncate_tx": lambda _: "TRUNCATE ledger_transactions CASCADE",
}


@pytest.mark.parametrize("name", MUTATIONS)
def test_ledger_history_is_immutable(session: Session, engine: Engine, name: str) -> None:
    wallet, escrow = _escrow_setup(session)
    tx = _post(session, [(wallet, D, 2_000), (escrow, C, 2_000)])
    session.commit()
    with engine.connect() as conn, pytest.raises(DBAPIError, match="append-only"):
        conn.execute(text(MUTATIONS[name](tx.id)))
    count = session.scalar(
        select(func.count()).select_from(LedgerEntry).where(LedgerEntry.transaction_id == tx.id)
    )
    assert count == 2


def test_account_purpose_must_match_type(session: Session) -> None:
    user = make_user(session)
    with pytest.raises(IntegrityError, match="purpose_matches_type"):
        make_account(session, AccountPurpose.USER_WALLET, AccountType.ASSET, owner=user)


def test_one_wallet_per_user(session: Session) -> None:
    user = make_user(session)
    make_account(session, AccountPurpose.USER_WALLET, AccountType.LIABILITY, owner=user)
    with pytest.raises(IntegrityError, match="uq_ledger_accounts_user_wallet"):
        make_account(session, AccountPurpose.USER_WALLET, AccountType.LIABILITY, owner=user)


def test_escrow_account_requires_deal(session: Session) -> None:
    with pytest.raises(IntegrityError, match="escrow_has_deal"):
        make_account(session, AccountPurpose.DEAL_ESCROW, AccountType.LIABILITY)
