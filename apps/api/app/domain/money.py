"""Money handling. SafePay only ever deals in whole Mongolian tögrög (MNT).

Rules:
* Amounts are plain ``int`` values in MNT. No floats, no Decimals, no minor units.
* Stored in PostgreSQL ``BIGINT`` columns, so the upper bound is 2**63 - 1.
* ``bool`` is rejected even though it subclasses ``int``.
"""

from typing import Final

CURRENCY: Final = "MNT"
MAX_MNT: Final = 2**63 - 1


class InvalidAmountError(ValueError):
    """Raised when a value is not a valid MNT amount."""


def validate_mnt(value: object, *, allow_zero: bool = False) -> int:
    """Return ``value`` if it is a valid integer MNT amount, else raise."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidAmountError(f"MNT amounts must be int, got {type(value).__name__}")
    if value < 0 or (value == 0 and not allow_zero):
        raise InvalidAmountError(f"MNT amount must be positive, got {value}")
    if value > MAX_MNT:
        raise InvalidAmountError("MNT amount exceeds BIGINT range")
    return value
