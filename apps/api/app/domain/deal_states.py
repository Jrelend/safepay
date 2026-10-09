"""Authoritative deal (escrow transaction) state machine.

The backend is the only component allowed to change a deal's state. Clients
request an *action*; the backend checks the action is legal for the current
state and the caller's role before applying it.

See ``docs/transaction-states.md`` for the narrative description.
"""

from dataclasses import dataclass
from enum import StrEnum


class DealStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_ACCEPTANCE = "PENDING_ACCEPTANCE"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    FUNDED = "FUNDED"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    DISPUTED = "DISPUTED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class DealAction(StrEnum):
    SUBMIT = "SUBMIT"
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"
    CANCEL = "CANCEL"
    EXPIRE = "EXPIRE"
    FUND = "FUND"
    MARK_DELIVERED = "MARK_DELIVERED"
    CONFIRM_RECEIPT = "CONFIRM_RECEIPT"
    AUTO_RELEASE = "AUTO_RELEASE"
    OPEN_DISPUTE = "OPEN_DISPUTE"
    REFUND = "REFUND"
    RESOLVE_RELEASE = "RESOLVE_RELEASE"
    RESOLVE_REFUND = "RESOLVE_REFUND"


class Actor(StrEnum):
    BUYER = "BUYER"
    SELLER = "SELLER"
    SYSTEM = "SYSTEM"
    ADMIN = "ADMIN"


class LedgerEffect(StrEnum):
    """Which simulated ledger posting must accompany a transition (atomically)."""

    NONE = "NONE"
    HOLD_IN_ESCROW = "HOLD_IN_ESCROW"
    RELEASE_TO_SELLER = "RELEASE_TO_SELLER"
    REFUND_TO_BUYER = "REFUND_TO_BUYER"


@dataclass(frozen=True, slots=True)
class Transition:
    source: DealStatus
    action: DealAction
    target: DealStatus
    actors: frozenset[Actor]
    ledger_effect: LedgerEffect = LedgerEffect.NONE


_B = Actor.BUYER
_S = Actor.SELLER
_SYS = Actor.SYSTEM
_ADM = Actor.ADMIN
_DS = DealStatus
_HOLD = LedgerEffect.HOLD_IN_ESCROW
_RELEASE = LedgerEffect.RELEASE_TO_SELLER
_REFUND = LedgerEffect.REFUND_TO_BUYER
_DA = DealAction


def _t(
    source: DealStatus,
    action: DealAction,
    target: DealStatus,
    *actors: Actor,
    effect: LedgerEffect = LedgerEffect.NONE,
) -> Transition:
    return Transition(source, action, target, frozenset(actors), effect)


TRANSITIONS: tuple[Transition, ...] = (
    _t(_DS.DRAFT, _DA.SUBMIT, _DS.PENDING_ACCEPTANCE, _B, _S),
    _t(_DS.DRAFT, _DA.CANCEL, _DS.CANCELLED, _B, _S),
    _t(_DS.PENDING_ACCEPTANCE, _DA.ACCEPT, _DS.AWAITING_PAYMENT, _B, _S),
    _t(_DS.PENDING_ACCEPTANCE, _DA.DECLINE, _DS.CANCELLED, _B, _S),
    _t(_DS.PENDING_ACCEPTANCE, _DA.CANCEL, _DS.CANCELLED, _B, _S),
    _t(_DS.PENDING_ACCEPTANCE, _DA.EXPIRE, _DS.EXPIRED, _SYS),
    _t(_DS.AWAITING_PAYMENT, _DA.FUND, _DS.FUNDED, _B, effect=_HOLD),
    _t(_DS.AWAITING_PAYMENT, _DA.CANCEL, _DS.CANCELLED, _B, _S),
    _t(_DS.AWAITING_PAYMENT, _DA.EXPIRE, _DS.EXPIRED, _SYS),
    _t(_DS.FUNDED, _DA.MARK_DELIVERED, _DS.DELIVERED, _S),
    _t(_DS.FUNDED, _DA.REFUND, _DS.REFUNDED, _S, _ADM, effect=_REFUND),
    _t(_DS.FUNDED, _DA.OPEN_DISPUTE, _DS.DISPUTED, _B, _S),
    _t(_DS.DELIVERED, _DA.CONFIRM_RECEIPT, _DS.COMPLETED, _B, effect=_RELEASE),
    _t(_DS.DELIVERED, _DA.AUTO_RELEASE, _DS.COMPLETED, _SYS, effect=_RELEASE),
    _t(_DS.DELIVERED, _DA.OPEN_DISPUTE, _DS.DISPUTED, _B, _S),
    _t(_DS.DELIVERED, _DA.REFUND, _DS.REFUNDED, _S, _ADM, effect=_REFUND),
    _t(_DS.DISPUTED, _DA.RESOLVE_RELEASE, _DS.COMPLETED, _ADM, effect=_RELEASE),
    _t(_DS.DISPUTED, _DA.RESOLVE_REFUND, _DS.REFUNDED, _ADM, effect=_REFUND),
)

TERMINAL_STATES: frozenset[DealStatus] = frozenset(
    {_DS.COMPLETED, _DS.REFUNDED, _DS.CANCELLED, _DS.EXPIRED}
)

# States in which the deal's escrow account must hold exactly the deal amount.
ESCROW_HELD_STATES: frozenset[DealStatus] = frozenset({_DS.FUNDED, _DS.DELIVERED, _DS.DISPUTED})

_INDEX: dict[tuple[DealStatus, DealAction], Transition] = {
    (t.source, t.action): t for t in TRANSITIONS
}


class IllegalTransitionError(Exception):
    def __init__(self, status: DealStatus, action: DealAction, actor: Actor) -> None:
        super().__init__(f"{actor} may not {action} a deal in state {status}")
        self.status = status
        self.action = action
        self.actor = actor


def resolve_transition(status: DealStatus, action: DealAction, actor: Actor) -> Transition:
    """Return the transition for ``action`` by ``actor`` from ``status`` or raise."""
    transition = _INDEX.get((status, action))
    if transition is None or actor not in transition.actors:
        raise IllegalTransitionError(status, action, actor)
    return transition


def allowed_actions(status: DealStatus, actor: Actor) -> list[DealAction]:
    return [t.action for t in TRANSITIONS if t.source == status and actor in t.actors]
