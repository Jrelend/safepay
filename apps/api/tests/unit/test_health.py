from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.db.session import get_engine
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    unreachable = create_engine(
        "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none",
        connect_args={"connect_timeout": 1},
    )
    app.dependency_overrides[get_engine] = lambda: unreachable
    with TestClient(app) as c:
        yield c


def test_health_is_ok_without_database(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["simulation_only"] is True


def test_every_response_is_marked_as_simulation(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.headers["X-SafePay-Simulation"] == "true"
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["X-Request-ID"]


def test_request_id_is_propagated(client: TestClient) -> None:
    resp = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert resp.headers["X-Request-ID"] == "abc-123"


def test_oversized_request_id_is_replaced(client: TestClient) -> None:
    resp = client.get("/health", headers={"X-Request-ID": "x" * 200})
    assert resp.headers["X-Request-ID"] != "x" * 200


def test_ready_reports_503_when_database_unreachable(client: TestClient) -> None:
    resp = client.get("/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] == {"ok": False, "detail": "database unavailable"}
    assert "nobody" not in resp.text  # credentials never leak
