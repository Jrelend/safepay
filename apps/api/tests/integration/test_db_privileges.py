"""The application role cannot escalate privileges or tamper with financial history.

Every statement here is attempted as ``safepay_app`` and must be refused by
PostgreSQL itself (privileges or triggers), not by application code.
"""

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.domain.deal_states import Actor, DealAction
from tests.integration.scenario import act, advance_to_funded, new_deal


def _refused(
    app_engine: Engine, statement: str, match: str, params: dict[str, object] | None = None
) -> None:
    with app_engine.connect() as conn, pytest.raises(DBAPIError, match=match):
        conn.execute(text(statement), params or {})
        conn.commit()


def test_app_role_attributes(app_engine: Engine) -> None:
    with app_engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls,
                       rolinherit,
                       pg_has_role(current_user, 'safepay_migrator', 'MEMBER') AS is_migrator,
                       (SELECT count(*) FROM pg_class WHERE relowner = r.oid) AS owned,
                       (SELECT count(*) FROM pg_proc WHERE proowner = r.oid) AS owned_functions
                  FROM pg_roles r WHERE rolname = current_user
                """
            )
        ).one()
    assert row == (False, False, False, False, False, False, False, 0, 0)


def test_financial_objects_are_owned_by_migrator(engine: Engine) -> None:
    with engine.connect() as conn:
        owners = set(
            conn.execute(
                text(
                    """
                    SELECT pg_get_userbyid(c.relowner) FROM pg_class c
                      JOIN pg_namespace n ON n.oid = c.relnamespace
                     WHERE n.nspname = 'public'
                    UNION
                    SELECT pg_get_userbyid(p.proowner) FROM pg_proc p
                      JOIN pg_namespace n ON n.oid = p.pronamespace
                     WHERE n.nspname = 'public'
                    """
                )
            ).scalars()
        )
    assert owners == {"safepay_migrator"}


def test_app_can_execute_only_the_transition_function(engine: Engine) -> None:
    with engine.connect() as conn:
        executable = set(
            conn.execute(
                text(
                    """
                    SELECT p.proname FROM pg_proc p
                      JOIN pg_namespace n ON n.oid = p.pronamespace
                     WHERE n.nspname = 'public'
                       AND has_function_privilege('safepay_app', p.oid, 'EXECUTE')
                    """
                )
            ).scalars()
        )
    assert executable == {"safepay_transition_deal"}


PERMISSION_DENIED = "permission denied|must be owner|must be superuser"

LEDGER_TAMPERING = {
    "update_entry_amount": "UPDATE ledger_entries SET amount_mnt = amount_mnt + 1",
    "delete_entries": "DELETE FROM ledger_entries",
    "truncate_entries": "TRUNCATE ledger_entries",
    "update_transaction": "UPDATE ledger_transactions SET kind = 'X'",
    "delete_transactions": "DELETE FROM ledger_transactions",
    "truncate_transactions": "TRUNCATE ledger_transactions CASCADE",
    "insert_entry": (
        "INSERT INTO ledger_entries (transaction_id, account_id, direction, amount_mnt) "
        "SELECT transaction_id, account_id, direction, amount_mnt FROM ledger_entries LIMIT 1"
    ),
    "insert_transaction": (
        "INSERT INTO ledger_transactions (idempotency_key, kind) VALUES ('forged', 'FORGED')"
    ),
    "insert_account": (
        "INSERT INTO ledger_accounts (code, account_type, purpose) "
        "VALUES ('forged', 'REVENUE', 'FEE_REVENUE')"
    ),
    "update_account": "UPDATE ledger_accounts SET code = 'x'",
    "update_audit": "UPDATE audit_events SET action = 'tampered'",
    "update_audit_time": "UPDATE audit_events SET occurred_at = '2000-01-01'",
    "delete_audit": "DELETE FROM audit_events",
    "truncate_audit": "TRUNCATE audit_events",
    "update_deal_status": "UPDATE deals SET status = 'COMPLETED', version = version + 1",
    "update_transition_rules": "UPDATE deal_transitions SET actors = ARRAY['BUYER']",
    "insert_transition_rule": (
        "INSERT INTO deal_transitions VALUES ('FUNDED', 'CANCEL', 'CANCELLED', "
        "ARRAY['BUYER'], 'NONE')"
    ),
    "delete_idempotency": "DELETE FROM idempotency_records",
    "delete_participants": "DELETE FROM deal_participants",
    "delete_deals": "DELETE FROM deals",
}


@pytest.mark.parametrize("name", LEDGER_TAMPERING)
def test_app_cannot_tamper_with_financial_data(app_engine: Engine, name: str) -> None:
    sc = new_deal(app_engine)
    advance_to_funded(app_engine, sc)  # make sure there is real ledger/audit data
    _refused(app_engine, LEDGER_TAMPERING[name], PERMISSION_DENIED)


ESCALATION = {
    "disable_triggers": "ALTER TABLE ledger_entries DISABLE TRIGGER ALL",
    "disable_one_trigger": "ALTER TABLE ledger_entries DISABLE TRIGGER ledger_entries_balanced",
    "drop_trigger": "DROP TRIGGER ledger_entries_no_update_delete ON ledger_entries",
    "replication_role": "SET session_replication_role = replica",
    "replace_trigger_function": (
        "CREATE OR REPLACE FUNCTION safepay_forbid_mutation() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$"
    ),
    "make_function_invoker": (
        "ALTER FUNCTION safepay_transition_deal(uuid, text, text, uuid, integer, text) "
        "SECURITY INVOKER"
    ),
    "create_table": "CREATE TABLE evil (id int)",
    "create_function": ("CREATE FUNCTION evil() RETURNS int LANGUAGE sql AS 'SELECT 1'"),
    "create_temp_table": "CREATE TEMP TABLE evil (id int)",
    "become_superuser": "ALTER ROLE safepay_app SUPERUSER",
    "grant_bypassrls": "ALTER ROLE safepay_app BYPASSRLS",
    "join_migrator": "GRANT safepay_migrator TO safepay_app",
    "set_role_migrator": "SET ROLE safepay_migrator",
    "set_session_authorization": "SET SESSION AUTHORIZATION safepay_migrator",
    "drop_ledger": "DROP TABLE ledger_entries",
    "alter_ledger": "ALTER TABLE ledger_entries ADD COLUMN evil int",
    "copy_to_program": "COPY (SELECT 1) TO PROGRAM 'true'",
    "read_server_file": "SELECT pg_read_file('/etc/passwd')",
    "call_trigger_function": "SELECT safepay_forbid_mutation()",
    "create_schema": "CREATE SCHEMA evil",
}


@pytest.mark.parametrize("name", ESCALATION)
def test_app_cannot_escalate_or_disable_safety(app_engine: Engine, name: str) -> None:
    _refused(
        app_engine,
        ESCALATION[name],
        PERMISSION_DENIED + "|only superusers|not permitted",
    )


def test_self_grant_gains_nothing(app_engine: Engine) -> None:
    """A GRANT without grant option only warns in PostgreSQL; verify it changes nothing."""
    with app_engine.connect() as conn:
        conn.execute(text("GRANT UPDATE, DELETE, TRUNCATE ON ledger_entries TO safepay_app"))
        conn.commit()
        held = conn.execute(
            text(
                "SELECT has_table_privilege('ledger_entries', 'UPDATE') "
                "OR has_table_privilege('ledger_entries', 'DELETE') "
                "OR has_table_privilege('ledger_entries', 'TRUNCATE')"
            )
        ).scalar_one()
    assert held is False


def test_trigger_state_is_unchanged(engine: Engine) -> None:
    with engine.connect() as conn:
        disabled = conn.execute(
            text("SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgenabled = 'D'")
        ).scalar_one()
    assert disabled == 0


def test_app_cannot_create_deal_outside_draft(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    _refused(
        app_engine,
        "INSERT INTO deals (reference, title, description, amount_mnt, status, created_by_id) "
        "VALUES ('SP-FORGED1', 'x', '', 1, 'FUNDED', :buyer)",
        "must be created in DRAFT",
        {"buyer": sc.buyer_id},
    )


def test_deal_amount_is_frozen_after_draft(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    act(app_engine, sc, DealAction.SUBMIT, Actor.SELLER)
    _refused(
        app_engine,
        "UPDATE deals SET amount_mnt = 1, version = version + 1 WHERE id = :id",
        "amount is frozen",
        {"id": sc.deal_id},
    )


def test_deal_amount_editable_in_draft(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    with app_engine.begin() as conn:
        conn.execute(
            text("UPDATE deals SET amount_mnt = 99000, version = version + 1 WHERE id = :id"),
            {"id": sc.deal_id},
        )
        assert (
            conn.execute(
                text("SELECT amount_mnt FROM deals WHERE id = :id"), {"id": sc.deal_id}
            ).scalar_one()
            == 99000
        )


def test_version_must_increment(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    _refused(
        app_engine,
        "UPDATE deals SET title = 'no version bump' WHERE id = :id",
        "increment version",
        {"id": sc.deal_id},
    )
