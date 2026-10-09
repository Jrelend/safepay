from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, create_engine, pool, text

from app.core.config import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    settings = get_settings()
    return str(settings.migration_database_url or settings.database_url)


MIGRATION_ROLE = "safepay_migrator"


def _require_migration_role(connection: Connection) -> None:
    """Refuse to migrate as anything but the non-superuser schema owner.

    Checked before *any* revision runs: otherwise a superuser could create
    objects the least-privilege design does not expect it to own.
    """
    user, is_superuser = connection.execute(
        text("SELECT current_user, rolsuper FROM pg_roles WHERE rolname = current_user")
    ).one()
    if user != MIGRATION_ROLE or is_superuser:
        raise RuntimeError(
            f"SafePay: run migrations as {MIGRATION_ROLE} (connected as {user!r}, "
            f"superuser={is_superuser}); set MIGRATION_DATABASE_URL. See docs/SECURITY.md."
        )


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        _require_migration_role(connection)
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
