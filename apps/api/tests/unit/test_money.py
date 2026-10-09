import pytest

from app.domain.money import MAX_MNT, InvalidAmountError, validate_mnt


@pytest.mark.parametrize("value", [1, 1_000, 25_000_000, MAX_MNT])
def test_accepts_positive_integers(value: int) -> None:
    assert validate_mnt(value) == value


def test_zero_only_when_allowed() -> None:
    with pytest.raises(InvalidAmountError):
        validate_mnt(0)
    assert validate_mnt(0, allow_zero=True) == 0


@pytest.mark.parametrize("value", [-1, MAX_MNT + 1])
def test_rejects_out_of_range(value: int) -> None:
    with pytest.raises(InvalidAmountError):
        validate_mnt(value)


@pytest.mark.parametrize("value", [1.0, 10.5, "100", None, True, False])
def test_rejects_non_integers(value: object) -> None:
    with pytest.raises(InvalidAmountError):
        validate_mnt(value)
