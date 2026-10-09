"""Simulated double-entry ledger.

There is deliberately **no balance column** anywhere. Balances are derived by
summing immutable ``ledger_entries``. Rows in ``ledger_transactions`` and
``ledger_entries`` can never be updated or deleted (enforced by DB triggers);
corrections are made with new, reversing transactions.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.ledger import AccountPurpose, AccountType, EntryDirection, LedgerTransactionKind
from app.domain.money import CURRENCY
from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin, str_enum

_ESCROW_KINDS_SQL = ", ".join(f"'{k.value}'" for k in LedgerTransactionKind)


class LedgerAccount(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "ledger_accounts"
    __table_args__ = (
        CheckConstraint(f"currency = '{CURRENCY}'", name="currency_mnt"),
        CheckConstraint(
            "(purpose = 'USER_WALLET') = (owner_user_id IS NOT NULL)",
            name="wallet_has_owner",
        ),
        CheckConstraint(
            "(purpose = 'DEAL_ESCROW') = (deal_id IS NOT NULL)", name="escrow_has_deal"
        ),
        CheckConstraint(
            "(purpose = 'SIMULATED_CASH' AND account_type = 'ASSET')"
            " OR (purpose IN ('USER_WALLET', 'DEAL_ESCROW') AND account_type = 'LIABILITY')"
            " OR (purpose = 'FEE_REVENUE' AND account_type = 'REVENUE')",
            name="purpose_matches_type",
        ),
        # One wallet per user, one escrow account per deal, one of each system account.
        Index(
            "uq_ledger_accounts_user_wallet",
            "owner_user_id",
            unique=True,
            postgresql_where=text("purpose = 'USER_WALLET'"),
        ),
        Index(
            "uq_ledger_accounts_deal_escrow",
            "deal_id",
            unique=True,
            postgresql_where=text("purpose = 'DEAL_ESCROW'"),
        ),
        Index(
            "uq_ledger_accounts_system_purpose",
            "purpose",
            unique=True,
            postgresql_where=text("purpose IN ('SIMULATED_CASH', 'FEE_REVENUE')"),
        ),
    )

    code: Mapped[str] = mapped_column(String(64), unique=True)
    account_type: Mapped[AccountType] = mapped_column(str_enum(AccountType, "account_type"))
    purpose: Mapped[AccountPurpose] = mapped_column(str_enum(AccountPurpose, "account_purpose"))
    currency: Mapped[str] = mapped_column(String(3), default=CURRENCY, server_default=CURRENCY)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    deal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("deals.id", ondelete="RESTRICT"))


class LedgerTransaction(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A journal transaction grouping balanced entries. Immutable."""

    __tablename__ = "ledger_transactions"
    __table_args__ = (
        CheckConstraint("reverses_transaction_id <> id", name="not_self_reversing"),
        CheckConstraint(
            f"kind NOT IN ({_ESCROW_KINDS_SQL}) OR deal_id IS NOT NULL",
            name="escrow_kind_has_deal",
        ),
        # No double funding / release / refund: each escrow kind at most once per deal...
        Index(
            "uq_ledger_transactions_deal_escrow_kind",
            "deal_id",
            "kind",
            unique=True,
            postgresql_where=text(f"kind IN ({_ESCROW_KINDS_SQL})"),
        ),
        # ...and a deal is settled (released OR refunded) at most once.
        Index(
            "uq_ledger_transactions_deal_settlement",
            "deal_id",
            unique=True,
            postgresql_where=text("kind IN ('ESCROW_RELEASE', 'ESCROW_REFUND')"),
        ),
    )

    # Client- or server-supplied key; replaying the same request must not post twice.
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("deals.id", ondelete="RESTRICT"), index=True
    )
    description: Mapped[str] = mapped_column(String(255), default="")
    # Set when this transaction reverses an earlier one (corrections never edit history).
    reverses_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ledger_transactions.id", ondelete="RESTRICT"), unique=True
    )

    entries: Mapped[list["LedgerEntry"]] = relationship(back_populates="transaction")


class LedgerEntry(UUIDPrimaryKeyMixin, Base):
    """One side of a journal transaction. Immutable."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint("amount_mnt > 0", name="amount_positive"),
        Index("ix_ledger_entries_account_id_created_at", "account_id", "created_at"),
    )

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ledger_transactions.id", ondelete="RESTRICT"), index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ledger_accounts.id", ondelete="RESTRICT")
    )
    direction: Mapped[EntryDirection] = mapped_column(str_enum(EntryDirection, "entry_direction"))
    amount_mnt: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    transaction: Mapped[LedgerTransaction] = relationship(back_populates="entries")
