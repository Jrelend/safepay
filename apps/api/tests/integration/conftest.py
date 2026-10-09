"""Integration tests run against a real, disposable PostgreSQL database.

``TEST_DATABASE_URL`` must be a *superuser* URL for a database whose name ends
in ``_test``. Once per session the fixtures:

1. drop and recreate the ``public`` schema (superuser; only ever on *_test DBs),
2. run ``infra/postgres/bootstrap-roles.sql`` with ``psql`` to (re)create the
   ``safepay_migrator`` and ``safepay_app`` roles,
3. run ``alembic upgrade head`` as ``safepay_migrator``.

Tests then use the real roles: ``engine`` / ``session`` connect as the schema
owner (``safepay_migrator``) for invariants that must hold even for the owner,
and ``app_engine`` / ``app_session`` connect as the runtime ``safepay_app`` role.

CI sets ``REQUIRE_INTEGRATION_TESTS=1`` so a missing database fails loudly
instead of silently skipping. Role passwords come from ``TEST_MIGRATOR_PASSWORD``
/ ``TEST_APP_PASSWORD`` (test-only defaults); use a dedicated test cluster,
because the roles are cluster-wide and their passwords are reset here.
"""

import os
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Engine, create_engine, make_url, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_engine, get_sessionmaker
from app.domain.ledger import AccountPurpose, AccountType
from app.models import Deal, DealParticipant, LedgerAccount, ParticipantRole, User

API_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = API_ROOT.parents[1]
BOOTSTRAP_SQL = REPO_ROOT / "infra" / "postgres" / "bootstrap-roles.sql"
MIGRATOR_PASSWORD = os.environ.get("TEST_MIGRATOR_PASSWORD", "test-migrator-password")
APP_PASSWORD = os.environ.get("TEST_APP_PASSWORD", "test-app-password")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "integration" in item.path.parts:
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def admin_url() -> URL:
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        message = "TEST_DATABASE_URL not set; skipping PostgreSQL integration tests"
        if os.environ.get("REQUIRE_INTEGRATION_TESTS") == "1":
            pytest.fail(message.replace("skipping", "but REQUIRE_INTEGRATION_TESTS=1 for"))
        pytest.skip(message)
    url = make_url(raw)
    if not (url.database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must point at a database whose name ends in _test")
    if shutil.which("psql") is None:
        pytest.fail("psql is required to bootstrap the database roles")
    return url


def _role_url(admin_url: URL, role: str, password: str) -> URL:
    return admin_url.set(username=role, password=password)


def bootstrap_roles(url: URL) -> None:
    psql = shutil.which("psql")
    assert psql is not None
    env = {**os.environ, "PGPASSWORD": url.password or ""}
    subprocess.run(  # noqa: S603 - fixed argv, test-only
        [
            psql,
            "-X",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
            "-h",
            url.host or "localhost",
            "-p",
            str(url.port or 5432),
            "-U",
            url.username or "",
            "-d",
            url.database or "",
            "-v",
            f"dbname={url.database}",
            "-v",
            f"migrator_password={MIGRATOR_PASSWORD}",
            "-v",
            f"app_password={APP_PASSWORD}",
            "-f",
            str(BOOTSTRAP_SQL),
        ],
        check=True,
        env=env,
        capture_output=True,
    )


@pytest.fixture(scope="session")
def admin_engine(admin_url: URL) -> Iterator[Engine]:
    eng = create_engine(admin_url)
    with eng.begin() as conn:
        # DROP SCHEMA bypasses the append-only triggers; only ever done on *_test DBs.
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    bootstrap_roles(admin_url)
    migrator_url = _role_url(admin_url, "safepay_migrator", MIGRATOR_PASSWORD)
    app_url = _role_url(admin_url, "safepay_app", APP_PASSWORD)
    os.environ["MIGRATION_DATABASE_URL"] = migrator_url.render_as_string(hide_password=False)
    os.environ["DATABASE_URL"] = app_url.render_as_string(hide_password=False)
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    command.upgrade(Config(str(API_ROOT / "alembic.ini")), "head")
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def engine(admin_engine: Engine, admin_url: URL) -> Iterator[Engine]:
    """Schema owner (safepay_migrator): not a superuser, but owns every object."""
    eng = create_engine(_role_url(admin_url, "safepay_migrator", MIGRATOR_PASSWORD))
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def app_engine(admin_engine: Engine, admin_url: URL) -> Iterator[Engine]:
    """The runtime application role (safepay_app)."""
    eng = create_engine(_role_url(admin_url, "safepay_app", APP_PASSWORD))
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as s:
        yield s


@pytest.fixture
def app_session(app_engine: Engine) -> Iterator[Session]:
    with Session(app_engine, expire_on_commit=False) as s:
        yield s


def _code() -> str:
    return uuid.uuid4().hex[:12].upper()


def make_user(session: Session) -> User:
    user = User(phone_e164=f"+976{uuid.uuid4().int % 10**8:08d}", display_name="Тест хэрэглэгч")
    session.add(user)
    session.flush()
    return user


def make_deal(session: Session, creator: User, amount_mnt: int = 150_000) -> Deal:
    deal = Deal(
        reference=f"SP-{_code()[:8]}",
        title="Хуучин утас",
        amount_mnt=amount_mnt,
        created_by_id=creator.id,
    )
    session.add(deal)
    session.flush()
    return deal


def make_account(
    session: Session,
    purpose: AccountPurpose,
    account_type: AccountType,
    *,
    owner: User | None = None,
    deal: Deal | None = None,
) -> LedgerAccount:
    account = LedgerAccount(
        code=f"{purpose.value}:{_code()}",
        purpose=purpose,
        account_type=account_type,
        owner_user_id=owner.id if owner else None,
        deal_id=deal.id if deal else None,
    )
    session.add(account)
    session.flush()
    return account


def add_participant(session: Session, deal: Deal, user: User, role: ParticipantRole) -> None:
    session.add(DealParticipant(deal_id=deal.id, user_id=user.id, role=role))
    session.flush()
