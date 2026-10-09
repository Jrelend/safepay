"""Deal terms vocabulary (pure)."""

from enum import StrEnum
from typing import Final


class ItemType(StrEnum):
    PHYSICAL_GOODS = "PHYSICAL_GOODS"
    DIGITAL_GOODS = "DIGITAL_GOODS"
    SERVICE = "SERVICE"


class DeliveryMethod(StrEnum):
    FACE_TO_FACE = "FACE_TO_FACE"
    COURIER = "COURIER"
    DIGITAL = "DIGITAL"


MIN_INSPECTION_DAYS: Final = 1
MAX_INSPECTION_DAYS: Final = 14
DEFAULT_INSPECTION_DAYS: Final = 3
# Deals waiting for acceptance or payment expire after this many idle days.
EXPIRY_DAYS: Final = 7

MIN_AMOUNT_MNT: Final = 100
MAX_AMOUNT_MNT: Final = 100_000_000_000


class IncompatibleTermsError(ValueError):
    pass


def check_terms(item_type: ItemType, delivery_method: DeliveryMethod) -> None:
    """Digital goods are delivered digitally; physical goods never are."""
    if item_type is ItemType.DIGITAL_GOODS and delivery_method is not DeliveryMethod.DIGITAL:
        raise IncompatibleTermsError("digital goods must use DIGITAL delivery")
    if item_type is ItemType.PHYSICAL_GOODS and delivery_method is DeliveryMethod.DIGITAL:
        raise IncompatibleTermsError("physical goods cannot use DIGITAL delivery")
