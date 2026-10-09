import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_simulation_only_cannot_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYMENTS_SIMULATION_ONLY", "false")
    with pytest.raises(ValidationError):
        Settings()


def test_defaults_are_simulation_only() -> None:
    assert Settings().payments_simulation_only is True
