"""Concurrency protections that exist in Phase 0 (two independent DB sessions)."""

import uuid

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.domain.deal_states import DealStatus
from app.domain.ledger import AccountPurpose, AccountType, EntryDirection
from app.models import Deal, LedgerEntry, LedgerTransaction
from tests.integration.conftest import make_account, make_deal, make_user


def test_optimistic_lock_rejects_lost_update(engine: Engine) -> None:
    with Session(engine) as setup:
        deal_id = make_deal(setup, make_user(setup)).id
        setup.commit()

    with Session(engine) as first, Session(engine) as second:
        a = first.get_one(Deal, deal_id)
        b = second.get_one(Deal, deal_id)
        a.status = DealStatus.PENDING_ACCEPTANCE
        first.commit()
        b.status = DealStatus.CANCELLED
        with pytest.raises(StaleDataError):
            second.commit()

    with Session(engine) as check:
        deal = check.get_one(Deal, deal_id)
        assert deal.status is DealStatus.PENDING_ACCEPTANCE
        assert deal.version == 2


def test_concurrent_postings_with_same_idempotency_key_post_once(engine: Engine) -> None:
    with Session(engine) as setup:
        user = make_user(setup)
        deal = make_deal(setup, user)
        wallet = make_account(setup, AccountPurpose.USER_WALLET, AccountType.LIABILITY, owner=user)
        escrow = make_account(setup, AccountPurpose.DEAL_ESCROW, AccountType.LIABILITY, deal=deal)
        setup.commit()
        deal_id, amount = deal.id, deal.amount_mnt
        wallet_id, escrow_id = wallet.id, escrow.id
    key = f"{deal_id}:FUND:{uuid.uuid4()}"

    def post(session: Session) -> None:
        tx = LedgerTransaction(idempotency_key=key, kind="FUND", deal_id=deal_id)
        session.add(tx)
        session.flush()
        session.add_all(
            [
                LedgerEntry(
                    transaction_id=tx.id,
                    account_id=wallet_id,
                    direction=EntryDirection.DEBIT,
                    amount_mnt=amount,
                ),
                LedgerEntry(
                    transaction_id=tx.id,
                    account_id=escrow_id,
                    direction=EntryDirection.CREDIT,
                    amount_mnt=amount,
                ),
            ]
        )
        session.flush()

    with Session(engine) as first, Session(engine) as second:
        post(first)
        first.commit()
        with pytest.raises(IntegrityError, match="idempotency_key"):
            post(second)

    with Session(engine) as check:
        count = check.query(LedgerTransaction).filter_by(idempotency_key=key).count()
        assert count == 1
