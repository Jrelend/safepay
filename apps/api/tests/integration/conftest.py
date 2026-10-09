"""Integration tests run against a real, disposable PostgreSQL database.

Set ``TEST_DATABASE_URL`` (the database name must end in ``_test``). CI also
sets ``REQUIRE_INTEGRATION_TESTS=1`` so a missing database fails loudly
instead of silently skipping. The schema
is dropped and rebuilt with ``alembic upgrade head`` once per session, so the
tests exercise the real migration including its triggers. They are skipped
when no test database is configured.
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_engine, get_sessionmaker
from app.domain.ledger import AccountPurpose, AccountType
from app.models import Deal, LedgerAccount, User

API_ROOT = Path(__file__).resolve().parents[2]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "integration" in item.path.parts:
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        message = "TEST_DATABASE_URL not set; skipping PostgreSQL integration tests"
        if os.environ.get("REQUIRE_INTEGRATION_TESTS") == "1":
            pytest.fail(message.replace("skipping", "but REQUIRE_INTEGRATION_TESTS=1 for"))
        pytest.skip(message)
    database = make_url(url).database or ""
    if not database.endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must point at a database whose name ends in _test")
    return url


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    eng = create_engine(database_url)
    with eng.begin() as conn:
        # DROP SCHEMA bypasses the append-only triggers; only ever done on *_test DBs.
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    os.environ["DATABASE_URL"] = database_url
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    command.upgrade(Config(str(API_ROOT / "alembic.ini")), "head")
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as s:
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
