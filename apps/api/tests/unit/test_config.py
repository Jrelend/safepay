import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.mark.parametrize("value", ["false", "False", "0", "no", "off"])
def test_simulation_only_cannot_be_disabled(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("PAYMENTS_SIMULATION_ONLY", value)
    with pytest.raises(ValidationError, match="must be true"):
        Settings()


@pytest.mark.parametrize("value", ["true", "True", "1"])
def test_simulation_only_accepts_true_from_environment(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Regression: compose sets PAYMENTS_SIMULATION_ONLY="true" as a string."""
    monkeypatch.setenv("PAYMENTS_SIMULATION_ONLY", value)
    assert Settings().payments_simulation_only is True


def test_simulation_only_rejects_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYMENTS_SIMULATION_ONLY", "maybe")
    with pytest.raises(ValidationError):
        Settings()


def test_defaults_are_simulation_only() -> None:
    assert Settings().payments_simulation_only is True
