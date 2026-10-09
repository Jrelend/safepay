from collections import deque

import pytest

from app.domain.deal_states import (
    ESCROW_HELD_STATES,
    TERMINAL_STATES,
    TRANSITIONS,
    Actor,
    DealAction,
    DealStatus,
    IllegalTransitionError,
    LedgerEffect,
    Transition,
    allowed_actions,
    resolve_transition,
)


def test_transitions_are_unique_per_state_and_action() -> None:
    keys = [(t.source, t.action) for t in TRANSITIONS]
    assert len(keys) == len(set(keys))


def test_every_state_reachable_from_draft() -> None:
    seen = {DealStatus.DRAFT}
    queue = deque([DealStatus.DRAFT])
    while queue:
        current = queue.popleft()
        for t in TRANSITIONS:
            if t.source == current and t.target not in seen:
                seen.add(t.target)
                queue.append(t.target)
    assert seen == set(DealStatus)


def test_terminal_states_have_no_outgoing_transitions() -> None:
    assert not [t for t in TRANSITIONS if t.source in TERMINAL_STATES]


def test_every_non_terminal_state_can_reach_a_terminal_state() -> None:
    for state in set(DealStatus) - TERMINAL_STATES:
        assert any(t.source == state for t in TRANSITIONS), state


def test_every_transition_has_an_actor() -> None:
    assert all(t.actors for t in TRANSITIONS)


@pytest.mark.parametrize("transition", TRANSITIONS, ids=lambda t: f"{t.source}-{t.action}")
def test_ledger_effects_match_escrow_invariant(transition: Transition) -> None:
    """Money moves exactly when a deal enters or leaves the escrow-held states."""
    was_held = transition.source in ESCROW_HELD_STATES
    is_held = transition.target in ESCROW_HELD_STATES
    if not was_held and is_held:
        assert transition.ledger_effect is LedgerEffect.HOLD_IN_ESCROW
    elif was_held and not is_held:
        expected = {
            DealStatus.COMPLETED: LedgerEffect.RELEASE_TO_SELLER,
            DealStatus.REFUNDED: LedgerEffect.REFUND_TO_BUYER,
        }[transition.target]
        assert transition.ledger_effect is expected
    else:
        assert transition.ledger_effect is LedgerEffect.NONE


def test_only_buyer_can_fund() -> None:
    t = resolve_transition(DealStatus.AWAITING_PAYMENT, DealAction.FUND, Actor.BUYER)
    assert t.target is DealStatus.FUNDED
    for actor in (Actor.SELLER, Actor.SYSTEM, Actor.ADMIN):
        with pytest.raises(IllegalTransitionError):
            resolve_transition(DealStatus.AWAITING_PAYMENT, DealAction.FUND, actor)


def test_only_buyer_confirms_receipt() -> None:
    with pytest.raises(IllegalTransitionError):
        resolve_transition(DealStatus.DELIVERED, DealAction.CONFIRM_RECEIPT, Actor.SELLER)


def test_disputes_only_resolved_by_admin() -> None:
    assert allowed_actions(DealStatus.DISPUTED, Actor.BUYER) == []
    assert allowed_actions(DealStatus.DISPUTED, Actor.SELLER) == []
    assert set(allowed_actions(DealStatus.DISPUTED, Actor.ADMIN)) == {
        DealAction.RESOLVE_RELEASE,
        DealAction.RESOLVE_REFUND,
    }


def test_buyer_cannot_refund_themselves() -> None:
    with pytest.raises(IllegalTransitionError):
        resolve_transition(DealStatus.FUNDED, DealAction.REFUND, Actor.BUYER)


def test_cannot_cancel_after_funding() -> None:
    for state in ESCROW_HELD_STATES:
        for actor in Actor:
            assert DealAction.CANCEL not in allowed_actions(state, actor)


def test_unknown_action_for_state_is_rejected() -> None:
    with pytest.raises(IllegalTransitionError):
        resolve_transition(DealStatus.COMPLETED, DealAction.OPEN_DISPUTE, Actor.BUYER)
