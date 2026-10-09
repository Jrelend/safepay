"""Apply a deal state transition (and its simulated escrow posting) atomically.

This is a service, not an HTTP endpoint. All rules are enforced inside
PostgreSQL by ``safepay_transition_deal`` (SECURITY DEFINER, owned by
``safepay_migrator``): row lock, legal transition, acting participant, escrow
posting at most once, version bump, audit event. This module adds the
request-level idempotency layer and maps database errors to Python exceptions.

Call it inside ``atomic(session)``; nothing is committed until that block ends.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.domain.deal_states import Actor, DealAction, DealStatus
from app.services.idempotency import run_idempotent

SCOPE = "deal.transition"


def idempotency_scope(actor: Actor, actor_user_id: uuid.UUID | None) -> str:
    """Keys are namespaced per acting principal.

    One user's key can never collide with, block, or reveal the existence of
    another user's key; SYSTEM actions share one namespace.
    """
    return f"{SCOPE}:{actor_user_id}" if actor_user_id else f"{SCOPE}:{actor.value}"


class DealTransitionError(Exception):
    """Base class; ``sqlstate`` is the SafePay error code raised by PostgreSQL."""

    sqlstate = ""


class DealNotFoundError(DealTransitionError):
    sqlstate = "SPD01"


class StaleDealVersionError(DealTransitionError):
    sqlstate = "SPD02"


class TransitionNotAllowedError(DealTransitionError):
    sqlstate = "SPD03"


class ParticipantMismatchError(DealTransitionError):
    sqlstate = "SPD04"


class EscrowInvariantError(DealTransitionError):
    sqlstate = "SPD05"


_ERRORS: dict[str, type[DealTransitionError]] = {
    cls.sqlstate: cls
    for cls in (
        DealNotFoundError,
        StaleDealVersionError,
        TransitionNotAllowedError,
        ParticipantMismatchError,
        EscrowInvariantError,
    )
}


@dataclass(frozen=True, slots=True)
class TransitionResult:
    deal_id: uuid.UUID
    action: DealAction
    from_status: DealStatus
    to_status: DealStatus
    version: int
    ledger_transaction_id: uuid.UUID | None
    audit_event_id: uuid.UUID
    replayed: bool


def _db_message(exc: DBAPIError) -> str:
    diag = getattr(exc.orig, "diag", None)
    return str(getattr(diag, "message_primary", None) or exc.orig)


def transition_deal(
    session: Session,
    *,
    deal_id: uuid.UUID,
    action: DealAction,
    actor: Actor,
    actor_user_id: uuid.UUID | None,
    idempotency_key: str,
    expected_version: int | None = None,
    request_id: str | None = None,
) -> TransitionResult:
    request = {
        "deal_id": deal_id,
        "action": action.value,
        "actor": actor.value,
        "actor_user_id": actor_user_id,
        "expected_version": expected_version,
    }

    def operation() -> dict[str, Any]:
        try:
            row = session.execute(
                text(
                    "SELECT safepay_transition_deal("
                    ":deal_id, :action, :actor, :actor_user_id, :expected_version, :request_id)"
                ),
                {**request, "request_id": request_id},
            ).scalar_one()
        except DBAPIError as exc:
            error = _ERRORS.get(getattr(exc.orig, "sqlstate", "") or "")
            if error is None:
                raise
            raise error(_db_message(exc)) from exc
        result: dict[str, Any] = row
        return result

    outcome = run_idempotent(
        session,
        scope=idempotency_scope(actor, actor_user_id),
        key=idempotency_key,
        request=request,
        operation=operation,
    )
    data = outcome.response
    ledger_tx = data.get("ledger_transaction_id")
    return TransitionResult(
        deal_id=uuid.UUID(data["deal_id"]),
        action=DealAction(data["action"]),
        from_status=DealStatus(data["from_status"]),
        to_status=DealStatus(data["to_status"]),
        version=int(data["version"]),
        ledger_transaction_id=uuid.UUID(ledger_tx) if ledger_tx else None,
        audit_event_id=uuid.UUID(data["audit_event_id"]),
        replayed=outcome.replayed,
    )
