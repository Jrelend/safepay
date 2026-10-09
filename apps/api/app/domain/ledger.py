"""Double-entry rules for the *simulated* ledger.

No balance is ever stored or updated directly: an account balance is always
derived from its immutable entries. Every posting (journal transaction) must
contain at least two entries whose debits equal their credits.

The same invariant is enforced again inside PostgreSQL by a deferred
constraint trigger (see the initial Alembic migration), so a bug in Python
cannot commit an unbalanced transaction.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.domain.money import validate_mnt


class EntryDirection(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class AccountType(StrEnum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"


class AccountPurpose(StrEnum):
    # Platform-side mirror of simulated money entering/leaving the system.
    SIMULATED_CASH = "SIMULATED_CASH"
    # What the platform (simulatedly) owes a user.
    USER_WALLET = "USER_WALLET"
    # Funds held for a single deal while it is in escrow.
    DEAL_ESCROW = "DEAL_ESCROW"
    # Future: simulated platform fees.
    FEE_REVENUE = "FEE_REVENUE"


DEBIT_NORMAL: frozenset[AccountType] = frozenset({AccountType.ASSET, AccountType.EXPENSE})

PURPOSE_ACCOUNT_TYPE: dict[AccountPurpose, AccountType] = {
    AccountPurpose.SIMULATED_CASH: AccountType.ASSET,
    AccountPurpose.USER_WALLET: AccountType.LIABILITY,
    AccountPurpose.DEAL_ESCROW: AccountType.LIABILITY,
    AccountPurpose.FEE_REVENUE: AccountType.REVENUE,
}


@dataclass(frozen=True, slots=True)
class Posting:
    account_id: UUID
    direction: EntryDirection
    amount_mnt: int


class UnbalancedPostingError(ValueError):
    pass


def validate_postings(postings: Iterable[Posting]) -> list[Posting]:
    """Validate a proposed journal transaction and return it as a list."""
    items = list(postings)
    if len(items) < 2:
        raise UnbalancedPostingError("a journal transaction needs at least two entries")
    debit = credit = 0
    for p in items:
        validate_mnt(p.amount_mnt)
        if p.direction is EntryDirection.DEBIT:
            debit += p.amount_mnt
        else:
            credit += p.amount_mnt
    if debit != credit:
        raise UnbalancedPostingError(f"debits ({debit}) != credits ({credit})")
    if debit == 0:
        raise UnbalancedPostingError("journal transaction has no value")
    if len({p.account_id for p in items}) < 2:
        raise UnbalancedPostingError("a journal transaction must touch at least two accounts")
    return items


def account_balance(
    account_type: AccountType, entries: Iterable[tuple[EntryDirection, int]]
) -> int:
    """Derive a balance (in the account's normal direction) from its entries."""
    debit = credit = 0
    for direction, amount in entries:
        if direction is EntryDirection.DEBIT:
            debit += amount
        else:
            credit += amount
    return debit - credit if account_type in DEBIT_NORMAL else credit - debit
