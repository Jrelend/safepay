"""Static guarantees about the schema that do not need a database."""

from sqlalchemy import BigInteger

from app.models import Base

EXPECTED_TABLES = {
    "users",
    "deals",
    "deal_participants",
    "ledger_accounts",
    "ledger_transactions",
    "ledger_entries",
    "audit_events",
    "deal_transitions",
    "idempotency_records",
    "admins",
    "sessions",
    "auth_tokens",
    "email_outbox",
    "rate_limits",
    "disputes",
    "dispute_evidence",
    "notifications",
}


def test_expected_tables_exist() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_no_stored_balances() -> None:
    """Balances must be derived from ledger entries, never stored."""
    for table in Base.metadata.tables.values():
        for column in table.columns:
            assert "balance" not in column.name, f"{table.name}.{column.name}"


def test_money_columns_are_bigint_mnt() -> None:
    money_columns = [
        (table.name, column)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.name.endswith("_mnt") or "amount" in column.name
    ]
    assert money_columns, "expected at least one money column"
    for table_name, column in money_columns:
        assert column.name.endswith("_mnt"), f"{table_name}.{column.name} must end in _mnt"
        assert isinstance(column.type, BigInteger), f"{table_name}.{column.name}"
        assert not column.nullable
