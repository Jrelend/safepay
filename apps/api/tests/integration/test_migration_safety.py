"""Migration safety, each test against its own brand-new database.

* a new database initializes correctly with the right ownership;
* a migration that fails part-way rolls back completely;
* downgrades refuse to destroy data unless explicitly allowed.
"""

import argparse
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Engine, create_engine, text

from app.core.config import get_settings
from tests.integration.conftest import MIGRATOR_PASSWORD, bootstrap_roles

API_ROOT = Path(__file__).resolve().parents[2]
DB_NAME = "safepay_migration_safety_test"


def _alembic(*x_args: str) -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.cmd_opts = argparse.Namespace(x=list(x_args))
    return cfg


@pytest.fixture
def fresh_db(admin_engine: Engine, admin_url: URL) -> Iterator[Engine]:
    with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {DB_NAME}"))
    url = admin_url.set(database=DB_NAME)
    bootstrap_roles(url)
    migrator_url = url.set(username="safepay_migrator", password=MIGRATOR_PASSWORD)
    previous = os.environ.get("MIGRATION_DATABASE_URL")
    os.environ["MIGRATION_DATABASE_URL"] = migrator_url.render_as_string(hide_password=False)
    get_settings.cache_clear()
    eng = create_engine(url)
    try:
        yield eng
    finally:
        eng.dispose()
        if previous is not None:
            os.environ["MIGRATION_DATABASE_URL"] = previous
        get_settings.cache_clear()
        with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)"))


def _scalar(engine: Engine, sql: str) -> object:
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar()


def test_new_database_initializes_with_correct_ownership(fresh_db: Engine) -> None:
    command.upgrade(_alembic(), "head")
    assert _scalar(fresh_db, "SELECT version_num FROM alembic_version") == "0005"
    assert (
        _scalar(
            fresh_db,
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND pg_get_userbyid(c.relowner) <> 'safepay_migrator'",
        )
        == 0
    )
    assert (
        _scalar(
            fresh_db,
            "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public' AND pg_get_userbyid(p.proowner) <> 'safepay_migrator'",
        )
        == 0
    )
    assert (
        _scalar(
            fresh_db,
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()",
        )
        == "safepay_migrator"
    )
    assert _scalar(fresh_db, "SELECT count(*) FROM deal_transitions") == 18
    assert (
        _scalar(fresh_db, "SELECT count(*) FROM ledger_accounts WHERE purpose = 'SIMULATED_CASH'")
        == 1
    )


def test_failed_migration_rolls_back_completely(fresh_db: Engine) -> None:
    command.upgrade(_alembic(), "0001")
    # Sabotage: an object 0002 wants to create already exists (owned by the migrator).
    migrator = create_engine(os.environ["MIGRATION_DATABASE_URL"])
    with migrator.begin() as conn:
        conn.execute(text("CREATE TABLE idempotency_records (blocker int)"))
    migrator.dispose()

    with pytest.raises(Exception, match="already exists"):
        command.upgrade(_alembic(), "head")

    # Nothing from 0002 survived: no partial security state.
    assert _scalar(fresh_db, "SELECT version_num FROM alembic_version") == "0001"
    assert _scalar(fresh_db, "SELECT to_regclass('public.deal_transitions') IS NULL") is True
    assert (
        _scalar(fresh_db, "SELECT count(*) FROM pg_proc WHERE proname = 'safepay_transition_deal'")
        == 0
    )
    assert (
        _scalar(fresh_db, "SELECT count(*) FROM ledger_accounts WHERE purpose = 'SIMULATED_CASH'")
        == 0
    )


def test_downgrade_refuses_to_destroy_data(fresh_db: Engine) -> None:
    command.upgrade(_alembic(), "head")
    with fresh_db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (email, password_hash, display_name, status) "
                "VALUES ('keep@example.com', '!x', 'keep me', 'ACTIVE')"
            )
        )
    with pytest.raises(Exception, match="refusing to downgrade"):
        command.downgrade(_alembic(), "base")
    assert _scalar(fresh_db, "SELECT count(*) FROM users") == 1
    assert _scalar(fresh_db, "SELECT version_num FROM alembic_version") in ("0003", "0004", "0005")
    # Explicit, deliberate opt-in still works (after a backup).
    command.downgrade(_alembic("allow_data_loss=true"), "base")
    assert _scalar(fresh_db, "SELECT to_regclass('public.users') IS NULL") is True


def test_0003_upgrade_keeps_existing_rows(fresh_db: Engine) -> None:
    """Upgrading a populated 0002 database backfills instead of dropping data."""
    command.upgrade(_alembic(), "0002")
    with fresh_db.begin() as conn:
        user_id = conn.execute(
            text(
                "INSERT INTO users (phone_e164, display_name, status) "
                "VALUES ('+97688000001', 'legacy', 'ACTIVE') "
                "RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO deals "
                "(reference, title, description, amount_mnt, status, created_by_id) "
                "VALUES ('SP-LEGACY01', 'legacy deal', '', 5000, 'DRAFT', :u)"
            ),
            {"u": user_id},
        )
    command.upgrade(_alembic(), "head")
    assert _scalar(fresh_db, "SELECT count(*) FROM users WHERE email LIKE 'legacy+%'") == 1
    assert (
        _scalar(fresh_db, "SELECT count(*) FROM deals WHERE invite_token_hash ~ '^[0-9a-f]{64}$'")
        == 1
    )


def test_downgrade_of_0002_refuses_when_idempotency_records_exist(fresh_db: Engine) -> None:
    command.upgrade(_alembic(), "head")
    with fresh_db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO idempotency_records (scope, key, request_hash) "
                "VALUES ('t', 'k', repeat('a', 64))"
            )
        )
        conn.execute(text("UPDATE idempotency_records SET response = '{}' WHERE scope = 't'"))
    with pytest.raises(Exception, match="refusing to downgrade"):
        command.downgrade(_alembic(), "0001")
    assert _scalar(fresh_db, "SELECT version_num FROM alembic_version") == "0002"


def test_downgrade_below_0004_refuses_while_deals_are_delivered(fresh_db: Engine) -> None:
    """Going back to 0003 would re-enable time-based auto-release for DELIVERED deals."""
    command.upgrade(_alembic(), "head")
    assert _scalar(fresh_db, "SELECT auto_release_enabled FROM platform_policy") is False
    with fresh_db.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role = replica"))  # test-only setup
        user_id = conn.execute(
            text(
                "INSERT INTO users (email, password_hash, display_name, status) "
                "VALUES ('d@example.com', '!x', 'd', 'ACTIVE') RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO deals (reference, title, description, amount_mnt, status, "
                "created_by_id, invite_token_hash) VALUES ('SP-DELIVER1', 'Television', '', 5000, "
                "'DELIVERED', :u, repeat('a', 64))"
            ),
            {"u": user_id},
        )
    with pytest.raises(Exception, match="re-enable time-based automatic"):
        command.downgrade(_alembic(), "0003")
    assert _scalar(fresh_db, "SELECT version_num FROM alembic_version") in ("0004", "0005")
    command.downgrade(_alembic("allow_data_loss=true"), "0003")
    assert _scalar(fresh_db, "SELECT to_regclass('public.platform_policy') IS NULL") is True
