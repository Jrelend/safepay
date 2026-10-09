import uuid

import pytest

from app.domain.ledger import (
    PURPOSE_ACCOUNT_TYPE,
    AccountPurpose,
    AccountType,
    EntryDirection,
    Posting,
    UnbalancedPostingError,
    account_balance,
    validate_postings,
)
from app.domain.money import InvalidAmountError

D = EntryDirection.DEBIT
C = EntryDirection.CREDIT


def _acct() -> uuid.UUID:
    return uuid.uuid4()


def test_balanced_posting_is_valid() -> None:
    a, b = _acct(), _acct()
    postings = validate_postings([Posting(a, D, 50_000), Posting(b, C, 50_000)])
    assert len(postings) == 2


def test_multi_leg_balanced_posting_is_valid() -> None:
    escrow, seller, fee = _acct(), _acct(), _acct()
    validate_postings(
        [Posting(escrow, D, 100_000), Posting(seller, C, 99_000), Posting(fee, C, 1_000)]
    )


def test_unbalanced_posting_is_rejected() -> None:
    with pytest.raises(UnbalancedPostingError):
        validate_postings([Posting(_acct(), D, 100), Posting(_acct(), C, 99)])


def test_single_entry_is_rejected() -> None:
    with pytest.raises(UnbalancedPostingError):
        validate_postings([Posting(_acct(), D, 100)])


def test_same_account_both_sides_is_rejected() -> None:
    a = _acct()
    with pytest.raises(UnbalancedPostingError):
        validate_postings([Posting(a, D, 100), Posting(a, C, 100)])


@pytest.mark.parametrize("amount", [0, -5, 1.5])
def test_invalid_amounts_are_rejected(amount: int) -> None:
    with pytest.raises(InvalidAmountError):
        validate_postings([Posting(_acct(), D, amount), Posting(_acct(), C, amount)])


def test_balance_follows_normal_side() -> None:
    entries = [(C, 10_000), (C, 5_000), (D, 3_000)]
    assert account_balance(AccountType.LIABILITY, entries) == 12_000
    assert account_balance(AccountType.ASSET, entries) == -12_000


def test_every_purpose_has_an_account_type() -> None:
    assert set(PURPOSE_ACCOUNT_TYPE) == set(AccountPurpose)
