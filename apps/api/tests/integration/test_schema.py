from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from app.core.config import get_settings
from app.models import Base

API_ROOT = Path(__file__).resolve().parents[2]


def test_migrations_match_models(engine: Engine) -> None:
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_database_is_at_head(engine: Engine) -> None:
    heads = ScriptDirectory.from_config(Config(str(API_ROOT / "alembic.ini"))).get_heads()
    with engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    assert sorted(current) == sorted(heads)


def test_server_is_postgres_17_or_newer(engine: Engine) -> None:
    with engine.connect() as conn:
        version = int(conn.execute(text("SHOW server_version_num")).scalar_one())
    assert version >= 170000


@pytest.mark.parametrize("role", ["superuser", "safepay_app"])
def test_migrations_refuse_any_role_but_the_migrator(
    admin_engine: Engine, app_engine: Engine, monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    url = (admin_engine if role == "superuser" else app_engine).url
    monkeypatch.setenv("MIGRATION_DATABASE_URL", url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="run migrations as safepay_migrator"):
            command.upgrade(Config(str(API_ROOT / "alembic.ini")), "head")
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
