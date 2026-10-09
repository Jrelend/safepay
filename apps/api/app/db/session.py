"""Database engines and sessions (SQLAlchemy 2, synchronous psycopg 3).

Each FastAPI app instance owns exactly ONE engine, bound to one database role
(``safepay_app`` for the public API, ``safepay_admin`` for the admin API) and
stored on ``app.state``. Nothing in the request path uses a process-global
engine, so a process can never accidentally use another role's credentials.
"""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


def make_engine(settings: Settings) -> Engine:
    return create_engine(
        str(settings.database_url),
        pool_size=settings.db_pool_size,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_pre_ping=True,
        connect_args={"connect_timeout": settings.db_pool_timeout_seconds},
    )


def get_engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def get_sessionmaker(request: Request) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = request.app.state.sessionmaker
    return factory


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency yielding a session; callers own commit boundaries."""
    session = get_sessionmaker(request)()
    try:
        yield session
    finally:
        session.close()
