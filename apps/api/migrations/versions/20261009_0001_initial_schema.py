"""initial schema

Creates users, deals, deal participants, the simulated double-entry ledger
(accounts, transactions, entries) and the audit trail, plus database-level
safety guarantees that do not depend on application code:

* ledger_transactions, ledger_entries and audit_events are append-only
  (UPDATE, DELETE and TRUNCATE raise an error);
* every ledger transaction must, at COMMIT, have >= 2 entries on >= 2
  accounts with debits equal to credits (deferred constraint triggers);
* entries can only be added to a ledger transaction in the same database
  transaction that created it.

Revision ID: 0001
Revises:
Create Date: 2026-10-09 17:30:03.485844

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.safety import refuse_data_loss

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


APPEND_ONLY_TABLES = ("ledger_transactions", "ledger_entries", "audit_events")

SAFETY_SQL = r"""
CREATE FUNCTION safepay_forbid_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'SafePay: % on append-only table % is forbidden', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE FUNCTION safepay_stamp_ledger_transaction() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- now() is the start time of the current database transaction.
    NEW.created_at := now();
    RETURN NEW;
END;
$$;

CREATE FUNCTION safepay_guard_ledger_entry() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    header_created_at timestamptz;
BEGIN
    SELECT created_at INTO header_created_at
    FROM ledger_transactions WHERE id = NEW.transaction_id;
    IF header_created_at IS DISTINCT FROM now() THEN
        RAISE EXCEPTION 'SafePay: ledger transaction % is sealed; entries must be inserted '
                        'in the same database transaction', NEW.transaction_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    NEW.created_at := now();
    RETURN NEW;
END;
$$;

CREATE FUNCTION safepay_check_ledger_balanced() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    tx_id uuid;
    total_debit numeric;
    total_credit numeric;
    entry_count integer;
    account_count integer;
BEGIN
    IF TG_TABLE_NAME = 'ledger_transactions' THEN
        tx_id := NEW.id;
    ELSE
        tx_id := NEW.transaction_id;
    END IF;

    SELECT COALESCE(SUM(amount_mnt) FILTER (WHERE direction = 'DEBIT'), 0),
           COALESCE(SUM(amount_mnt) FILTER (WHERE direction = 'CREDIT'), 0),
           COUNT(*),
           COUNT(DISTINCT account_id)
      INTO total_debit, total_credit, entry_count, account_count
      FROM ledger_entries
     WHERE transaction_id = tx_id;

    IF entry_count < 2 OR account_count < 2 OR total_debit <> total_credit THEN
        RAISE EXCEPTION 'SafePay: ledger transaction % is unbalanced '
                        '(entries=%, accounts=%, debit=%, credit=%)',
                        tx_id, entry_count, account_count, total_debit, total_credit
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER ledger_transactions_stamp
    BEFORE INSERT ON ledger_transactions
    FOR EACH ROW EXECUTE FUNCTION safepay_stamp_ledger_transaction();

CREATE TRIGGER ledger_entries_guard
    BEFORE INSERT ON ledger_entries
    FOR EACH ROW EXECUTE FUNCTION safepay_guard_ledger_entry();

CREATE CONSTRAINT TRIGGER ledger_transactions_balanced
    AFTER INSERT ON ledger_transactions
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION safepay_check_ledger_balanced();

CREATE CONSTRAINT TRIGGER ledger_entries_balanced
    AFTER INSERT ON ledger_entries
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION safepay_check_ledger_balanced();
"""


def _create_safety_triggers() -> None:
    op.execute(SAFETY_SQL)
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_no_update_delete BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION safepay_forbid_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION safepay_forbid_mutation()"
        )


def _drop_safety_triggers() -> None:
    # Dropping the tables drops their triggers; only the functions remain.
    for fn in (
        "safepay_check_ledger_balanced",
        "safepay_guard_ledger_entry",
        "safepay_stamp_ledger_transaction",
        "safepay_forbid_mutation",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {fn}()")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("phone_e164", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "SUSPENDED",
                "CLOSED",
                name="user_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'SUSPENDED', 'CLOSED')", name=op.f("ck_users_user_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("phone_e164", name=op.f("uq_users_phone_e164")),
    )
    op.create_table(
        "deals",
        sa.Column("reference", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("amount_mnt", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="MNT", nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT",
                "PENDING_ACCEPTANCE",
                "AWAITING_PAYMENT",
                "FUNDED",
                "DELIVERED",
                "COMPLETED",
                "DISPUTED",
                "REFUNDED",
                "CANCELLED",
                "EXPIRED",
                name="deal_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("currency = 'MNT'", name=op.f("ck_deals_currency_mnt")),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PENDING_ACCEPTANCE', 'AWAITING_PAYMENT', 'FUNDED', 'DELIVERED', 'COMPLETED', 'DISPUTED', 'REFUNDED', 'CANCELLED', 'EXPIRED')",
            name=op.f("ck_deals_deal_status"),
        ),
        sa.CheckConstraint("amount_mnt > 0", name=op.f("ck_deals_amount_positive")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_deals_version_positive")),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_deals_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deals")),
        sa.UniqueConstraint("reference", name=op.f("uq_deals_reference")),
    )
    op.create_index("ix_deals_status", "deals", ["status"], unique=False)
    op.create_table(
        "audit_events",
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "actor_type",
            sa.Enum(
                "BUYER",
                "SELLER",
                "SYSTEM",
                "ADMIN",
                name="audit_actor_type",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("deal_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "data", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint(
            "actor_type IN ('BUYER', 'SELLER', 'SYSTEM', 'ADMIN')",
            name=op.f("ck_audit_events_audit_actor_type"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_events_actor_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"],
            ["deals.id"],
            name=op.f("fk_audit_events_deal_id_deals"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        "ix_audit_events_deal_id_occurred_at",
        "audit_events",
        ["deal_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_entity",
        "audit_events",
        ["entity_type", "entity_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "deal_participants",
        sa.Column("deal_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "BUYER",
                "SELLER",
                name="participant_role",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('BUYER', 'SELLER')", name=op.f("ck_deal_participants_participant_role")
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"],
            ["deals.id"],
            name=op.f("fk_deal_participants_deal_id_deals"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_deal_participants_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deal_participants")),
        sa.UniqueConstraint("deal_id", "role", name=op.f("uq_deal_participants_deal_id_role")),
        sa.UniqueConstraint(
            "deal_id", "user_id", name=op.f("uq_deal_participants_deal_id_user_id")
        ),
    )
    op.create_index(
        op.f("ix_deal_participants_user_id"), "deal_participants", ["user_id"], unique=False
    )
    op.create_table(
        "ledger_accounts",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column(
            "account_type",
            sa.Enum(
                "ASSET",
                "LIABILITY",
                "EQUITY",
                "REVENUE",
                "EXPENSE",
                name="account_type",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "purpose",
            sa.Enum(
                "SIMULATED_CASH",
                "USER_WALLET",
                "DEAL_ESCROW",
                "FEE_REVENUE",
                name="account_purpose",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=3), server_default="MNT", nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("deal_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(purpose = 'DEAL_ESCROW') = (deal_id IS NOT NULL)",
            name=op.f("ck_ledger_accounts_escrow_has_deal"),
        ),
        sa.CheckConstraint(
            "(purpose = 'SIMULATED_CASH' AND account_type = 'ASSET') OR (purpose IN ('USER_WALLET', 'DEAL_ESCROW') AND account_type = 'LIABILITY') OR (purpose = 'FEE_REVENUE' AND account_type = 'REVENUE')",
            name=op.f("ck_ledger_accounts_purpose_matches_type"),
        ),
        sa.CheckConstraint(
            "(purpose = 'USER_WALLET') = (owner_user_id IS NOT NULL)",
            name=op.f("ck_ledger_accounts_wallet_has_owner"),
        ),
        sa.CheckConstraint(
            "account_type IN ('ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE')",
            name=op.f("ck_ledger_accounts_account_type"),
        ),
        sa.CheckConstraint("currency = 'MNT'", name=op.f("ck_ledger_accounts_currency_mnt")),
        sa.CheckConstraint(
            "purpose IN ('SIMULATED_CASH', 'USER_WALLET', 'DEAL_ESCROW', 'FEE_REVENUE')",
            name=op.f("ck_ledger_accounts_account_purpose"),
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"],
            ["deals.id"],
            name=op.f("fk_ledger_accounts_deal_id_deals"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_ledger_accounts_owner_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger_accounts")),
        sa.UniqueConstraint("code", name=op.f("uq_ledger_accounts_code")),
    )
    op.create_index(
        "uq_ledger_accounts_deal_escrow",
        "ledger_accounts",
        ["deal_id"],
        unique=True,
        postgresql_where=sa.text("purpose = 'DEAL_ESCROW'"),
    )
    op.create_index(
        "uq_ledger_accounts_system_purpose",
        "ledger_accounts",
        ["purpose"],
        unique=True,
        postgresql_where=sa.text("purpose IN ('SIMULATED_CASH', 'FEE_REVENUE')"),
    )
    op.create_index(
        "uq_ledger_accounts_user_wallet",
        "ledger_accounts",
        ["owner_user_id"],
        unique=True,
        postgresql_where=sa.text("purpose = 'USER_WALLET'"),
    )
    op.create_table(
        "ledger_transactions",
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("deal_id", sa.Uuid(), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("reverses_transaction_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reverses_transaction_id <> id", name=op.f("ck_ledger_transactions_not_self_reversing")
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"],
            ["deals.id"],
            name=op.f("fk_ledger_transactions_deal_id_deals"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reverses_transaction_id"],
            ["ledger_transactions.id"],
            name=op.f("fk_ledger_transactions_reverses_transaction_id_ledger_transactions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger_transactions")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_ledger_transactions_idempotency_key")),
        sa.UniqueConstraint(
            "reverses_transaction_id", name=op.f("uq_ledger_transactions_reverses_transaction_id")
        ),
    )
    op.create_index(
        op.f("ix_ledger_transactions_deal_id"), "ledger_transactions", ["deal_id"], unique=False
    )
    op.create_table(
        "ledger_entries",
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column(
            "direction",
            sa.Enum(
                "DEBIT",
                "CREDIT",
                name="entry_direction",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("amount_mnt", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint(
            "direction IN ('DEBIT', 'CREDIT')", name=op.f("ck_ledger_entries_entry_direction")
        ),
        sa.CheckConstraint("amount_mnt > 0", name=op.f("ck_ledger_entries_amount_positive")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["ledger_accounts.id"],
            name=op.f("fk_ledger_entries_account_id_ledger_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["ledger_transactions.id"],
            name=op.f("fk_ledger_entries_transaction_id_ledger_transactions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger_entries")),
    )
    op.create_index(
        "ix_ledger_entries_account_id_created_at",
        "ledger_entries",
        ["account_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ledger_entries_transaction_id"), "ledger_entries", ["transaction_id"], unique=False
    )

    _create_safety_triggers()


def downgrade() -> None:
    refuse_data_loss(
        (
            "users",
            "deals",
            "deal_participants",
            "ledger_accounts",
            "ledger_transactions",
            "ledger_entries",
            "audit_events",
        )
    )
    op.drop_index(op.f("ix_ledger_entries_transaction_id"), table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_account_id_created_at", table_name="ledger_entries")
    op.drop_table("ledger_entries")
    op.drop_index(op.f("ix_ledger_transactions_deal_id"), table_name="ledger_transactions")
    op.drop_table("ledger_transactions")
    op.drop_index(
        "uq_ledger_accounts_user_wallet",
        table_name="ledger_accounts",
        postgresql_where=sa.text("purpose = 'USER_WALLET'"),
    )
    op.drop_index(
        "uq_ledger_accounts_system_purpose",
        table_name="ledger_accounts",
        postgresql_where=sa.text("purpose IN ('SIMULATED_CASH', 'FEE_REVENUE')"),
    )
    op.drop_index(
        "uq_ledger_accounts_deal_escrow",
        table_name="ledger_accounts",
        postgresql_where=sa.text("purpose = 'DEAL_ESCROW'"),
    )
    op.drop_table("ledger_accounts")
    op.drop_index(op.f("ix_deal_participants_user_id"), table_name="deal_participants")
    op.drop_table("deal_participants")
    op.drop_index("ix_audit_events_entity", table_name="audit_events")
    op.drop_index("ix_audit_events_deal_id_occurred_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_deals_status", table_name="deals")
    op.drop_table("deals")
    op.drop_table("users")
    _drop_safety_triggers()
