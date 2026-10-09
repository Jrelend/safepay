from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

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
