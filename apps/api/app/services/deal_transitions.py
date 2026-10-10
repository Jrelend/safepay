"""Deal state transitions and their simulated escrow postings.

Three entry points, each backed by a different PostgreSQL function and usable
only with a different database role:

* :func:`transition_deal`  — public API (``safepay_app``). The caller passes the
  *authenticated* user id; the database derives BUYER/SELLER from the
  participant row. SYSTEM and ADMIN are impossible on this path.
* :func:`system_transition` — background worker (``safepay_system``).
* :func:`admin_refund`, :func:`admin_resolve_dispute`, :func:`admin_set_user_status`
  — admin API (``safepay_admin``); the database checks the ``admins`` table.

All rules (row lock, legal transition, participant, escrow, version, audit,
notifications) are enforced inside PostgreSQL. Call these inside ``atomic``.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.domain.deal_states import DealAction, DealStatus
from app.services.idempotency import run_idempotent

SCOPE = "deal.transition"
PUBLIC_ACTIONS = frozenset(
    {
        DealAction.SUBMIT,
        DealAction.ACCEPT,
        DealAction.DECLINE,
        DealAction.CANCEL,
        DealAction.FUND,
        DealAction.MARK_DELIVERED,
        DealAction.CONFIRM_RECEIPT,
        DealAction.REFUND,
        DealAction.OPEN_DISPUTE,
    }
)


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


class UserNotEligibleError(DealTransitionError):
    sqlstate = "SPD06"


class ReasonRequiredError(DealTransitionError):
    sqlstate = "SPD07"


class NotYetEligibleError(DealTransitionError):
    sqlstate = "SPD08"


class NotAdministratorError(DealTransitionError):
    sqlstate = "SPD09"


class AutoReleaseDisabledError(DealTransitionError):
    """AUTO_RELEASE refused: platform_policy.auto_release_enabled is false (Beta default)."""

    sqlstate = "SPD10"


_ERRORS: dict[str, type[DealTransitionError]] = {
    cls.sqlstate: cls
    for cls in (
        DealNotFoundError,
        StaleDealVersionError,
        TransitionNotAllowedError,
        ParticipantMismatchError,
        EscrowInvariantError,
        UserNotEligibleError,
        ReasonRequiredError,
        NotYetEligibleError,
        NotAdministratorError,
        AutoReleaseDisabledError,
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
    dispute_id: uuid.UUID | None
    replayed: bool


def _db_message(exc: DBAPIError) -> str:
    diag = getattr(exc.orig, "diag", None)
    return str(getattr(diag, "message_primary", None) or exc.orig)


def call_db_function(session: Session, sql: str, params: Mapping[str, Any]) -> Any:
    """Run one SafePay DB function, mapping its SQLSTATEs to typed exceptions."""
    try:
        return session.execute(text(sql), dict(params)).scalar_one()
    except DBAPIError as exc:
        error = _ERRORS.get(getattr(exc.orig, "sqlstate", "") or "")
        if error is None:
            raise
        raise error(_db_message(exc)) from exc


def _result(data: Mapping[str, Any], *, replayed: bool) -> TransitionResult:
    ledger_tx = data.get("ledger_transaction_id")
    dispute = data.get("dispute_id")
    return TransitionResult(
        deal_id=uuid.UUID(data["deal_id"]),
        action=DealAction(data["action"]),
        from_status=DealStatus(data["from_status"]),
        to_status=DealStatus(data["to_status"]),
        version=int(data["version"]),
        ledger_transaction_id=uuid.UUID(ledger_tx) if ledger_tx else None,
        audit_event_id=uuid.UUID(data["audit_event_id"]),
        dispute_id=uuid.UUID(dispute) if dispute else None,
        replayed=replayed,
    )


def idempotency_scope(actor_user_id: uuid.UUID) -> str:
    """Keys are namespaced per authenticated user."""
    return f"{SCOPE}:{actor_user_id}"


def transition_deal(
    session: Session,
    *,
    deal_id: uuid.UUID,
    action: DealAction,
    actor_user_id: uuid.UUID,
    idempotency_key: str,
    expected_version: int | None = None,
    note: str | None = None,
    request_id: str | None = None,
) -> TransitionResult:
    if action not in PUBLIC_ACTIONS:
        raise TransitionNotAllowedError(f"{action} is not available to deal participants")
    request = {
        "deal_id": deal_id,
        "action": action.value,
        "actor_user_id": actor_user_id,
        "expected_version": expected_version,
        "note": note,
    }

    def operation() -> dict[str, Any]:
        result: dict[str, Any] = call_db_function(
            session,
            "SELECT safepay_transition_deal("
            ":deal_id, :action, :actor_user_id, :expected_version, :request_id, :note)",
            {**request, "request_id": request_id},
        )
        return result

    outcome = run_idempotent(
        session,
        scope=idempotency_scope(actor_user_id),
        key=idempotency_key,
        request=request,
        operation=operation,
    )
    return _result(outcome.response, replayed=outcome.replayed)


def system_transition(
    session: Session, *, deal_id: uuid.UUID, action: DealAction, request_id: str | None = None
) -> TransitionResult:
    """Worker only (safepay_system). Eligibility is re-checked by the database."""
    data = call_db_function(
        session,
        "SELECT safepay_system_transition_deal(:deal_id, :action, :request_id)",
        {"deal_id": deal_id, "action": action.value, "request_id": request_id},
    )
    return _result(data, replayed=False)


def admin_refund(
    session: Session,
    *,
    deal_id: uuid.UUID,
    admin_user_id: uuid.UUID,
    reason: str,
    request_id: str | None = None,
) -> TransitionResult:
    data = call_db_function(
        session,
        "SELECT safepay_admin_transition_deal(:deal_id, 'REFUND', :admin, :reason, :request_id)",
        {"deal_id": deal_id, "admin": admin_user_id, "reason": reason, "request_id": request_id},
    )
    return _result(data, replayed=False)


def admin_resolve_dispute(
    session: Session,
    *,
    dispute_id: uuid.UUID,
    outcome: str,
    admin_user_id: uuid.UUID,
    reason: str,
    request_id: str | None = None,
) -> TransitionResult:
    data = call_db_function(
        session,
        "SELECT safepay_admin_resolve_dispute(:dispute_id, :outcome, :admin, :reason, :request_id)",
        {
            "dispute_id": dispute_id,
            "outcome": outcome,
            "admin": admin_user_id,
            "reason": reason,
            "request_id": request_id,
        },
    )
    return _result(data, replayed=False)


def admin_set_user_status(
    session: Session, *, admin_user_id: uuid.UUID, user_id: uuid.UUID, status: str, reason: str
) -> None:
    try:
        session.execute(
            text("SELECT safepay_admin_set_user_status(:admin, :user, :status, :reason)"),
            {"admin": admin_user_id, "user": user_id, "status": status, "reason": reason},
        )
    except DBAPIError as exc:
        error = _ERRORS.get(getattr(exc.orig, "sqlstate", "") or "")
        if error is None:
            raise
        raise error(_db_message(exc)) from exc
