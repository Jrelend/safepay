from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.db.session import get_engine
from app.main import create_app


def test_ready_against_migrated_database(engine: Engine) -> None:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: engine
    with TestClient(app) as client:
        resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "ready",
        "checks": {
            "database": {"ok": True, "detail": None},
            "migrations": {"ok": True, "detail": None},
        },
    }
