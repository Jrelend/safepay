"""Startup refusals, redacted logging and DB-outage behaviour."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app, redact_path

SAFE_STAGING = {
    "app_env": "staging",
    "public_web_url": "https://beta.example.mn",
    "cors_allowed_origins": ["https://beta.example.mn"],
}


def _settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


def test_staging_accepts_a_locked_down_configuration() -> None:
    s = _settings(**SAFE_STAGING)
    assert s.secure_cookies and not s.mailbox_enabled


@pytest.mark.parametrize(
    "override",
    [
        {"dev_mailbox_enabled": True},
        {"cookie_secure": False},
        {"public_web_url": "http://beta.example.mn"},
        {"cors_allowed_origins": ["http://beta.example.mn"]},
    ],
)
@pytest.mark.parametrize("env", ["staging", "production"])
def test_deployed_environments_refuse_unsafe_settings(env: str, override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match=f"unsafe {env} configuration"):
        _settings(**{**SAFE_STAGING, "app_env": env, **override})


@pytest.mark.parametrize(
    "override", [{"payments_simulation_only": False}, {"payment_mode": "live"}]
)
def test_real_payment_mode_refuses_to_start(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _settings(**override)


def test_invite_tokens_are_redacted_from_access_logs() -> None:
    assert redact_path("/invites/AbC_123-xyz/join") == "/invites/[redacted]/join"
    assert redact_path("/invites/AbC_123-xyz") == "/invites/[redacted]"
    assert redact_path("/deals/1234") == "/deals/1234"


def test_database_outage_returns_clean_503() -> None:
    """Scenario L: the API stays up and answers with a retryable JSON error."""
    app = create_app(
        _settings(
            database_url="postgresql+psycopg://safepay_app:x@127.0.0.1:1/safepay",
            db_pool_timeout_seconds=1,
            cors_allowed_origins=["http://web.test"],
        )
    )
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set("safepay_session", "x" * 43)
    r = client.get("/deals")
    assert r.status_code == 503
    assert r.json() == {
        "error": {
            "code": "service_unavailable",
            "message": "temporarily unavailable, try again shortly",
        }
    }
    assert "psycopg" not in r.text and "127.0.0.1" not in r.text
    assert r.headers["retry-after"] == "5"
    assert client.get("/health").status_code == 200  # liveness is DB-independent
    assert client.get("/ready").status_code == 503
