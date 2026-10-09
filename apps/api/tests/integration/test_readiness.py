from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.db.session import get_engine
from app.main import create_app


def _ready(engine: Engine) -> tuple[int, dict[str, Any]]:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: engine
    with TestClient(app) as client:
        resp = client.get("/ready")
    return resp.status_code, resp.json()


def test_ready_as_least_privileged_app_role(app_engine: Engine) -> None:
    status, body = _ready(app_engine)
    assert status == 200
    assert body == {
        "status": "ready",
        "checks": {
            "database": {"ok": True, "detail": None},
            "migrations": {"ok": True, "detail": None},
            "db_role": {"ok": True, "detail": None},
        },
    }


def test_not_ready_when_connected_as_schema_owner(engine: Engine) -> None:
    status, body = _ready(engine)
    assert status == 503
    assert body["checks"]["db_role"]["ok"] is False


def test_not_ready_when_connected_as_superuser(admin_engine: Engine) -> None:
    status, body = _ready(admin_engine)
    assert status == 503
    assert body["checks"]["db_role"]["ok"] is False
