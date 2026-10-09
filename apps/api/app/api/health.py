"""Liveness and readiness probes.

* ``GET /health`` — liveness. Never touches the database; only says the process is up.
* ``GET /ready``  — readiness. Verifies the database is reachable and that the
  schema is at the latest Alembic revision. Returns 503 otherwise so load
  balancers / Docker health checks stop routing traffic.
"""

import logging
from pathlib import Path
from typing import Literal

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import EngineDep, SettingsDep

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    environment: str
    simulation_only: bool


class CheckResult(BaseModel):
    ok: bool
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, CheckResult]


def expected_migration_heads() -> set[str]:
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
    return set(script.get_heads())


@router.get("/health", response_model=HealthResponse)
def health(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
        simulation_only=settings.payments_simulation_only,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
def ready(
    response: Response,
    engine: EngineDep,
    settings: SettingsDep,
) -> ReadinessResponse:
    checks: dict[str, CheckResult] = {}
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('statement_timeout', :ms, true)"),
                {"ms": str(settings.readiness_db_timeout_ms)},
            )
            conn.execute(text("SELECT 1"))
            checks["database"] = CheckResult(ok=True)
            current = set(conn.execute(text("SELECT version_num FROM alembic_version")).scalars())
            expected = expected_migration_heads()
            if current == expected:
                checks["migrations"] = CheckResult(ok=True)
            else:
                checks["migrations"] = CheckResult(
                    ok=False,
                    detail=f"database at {sorted(current)}, code expects {sorted(expected)}",
                )
    except SQLAlchemyError as exc:
        # Do not leak connection strings or driver internals to callers.
        logger.warning("readiness check failed: %s", type(exc).__name__)
        checks.setdefault("database", CheckResult(ok=False, detail="database unavailable"))
        checks.setdefault("migrations", CheckResult(ok=False, detail="not checked"))

    is_ready = all(c.ok for c in checks.values())
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ready" if is_ready else "not_ready", checks=checks)
