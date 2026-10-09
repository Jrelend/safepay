"""Which DB role may execute which SafePay function, and the worker's real behaviour."""

import uuid

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.domain.deal_states import Actor, DealAction, DealStatus
from app.worker import run_once
from tests.integration.scenario import act, advance_to_awaiting_payment, backdate, new_deal

PUBLIC = "safepay_transition_deal"
SYSTEM = "safepay_system_transition_deal"
ADMIN = {
    "safepay_admin_transition_deal",
    "safepay_admin_resolve_dispute",
    "safepay_admin_set_user_status",
}
EXPECTED = {
    "safepay_app": {PUBLIC},
    "safepay_system": {SYSTEM},
    "safepay_admin": ADMIN,
}


def test_function_privilege_matrix(engine: Engine) -> None:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT r.rolname, p.proname FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid = p.pronamespace AND n.nspname = 'public' "
                "CROSS JOIN pg_roles r "
                "WHERE r.rolname IN ('safepay_app', 'safepay_system', 'safepay_admin') "
                "AND has_function_privilege(r.oid, p.oid, 'EXECUTE')"
            )
        ).all()
    granted: dict[str, set[str]] = {role: set() for role in EXPECTED}
    for role, fn in rows:
        granted[role].add(fn)
    assert granted == EXPECTED


@pytest.mark.parametrize(
    ("role", "sql"),
    [
        ("app", f"SELECT {SYSTEM}(gen_random_uuid(), 'AUTO_RELEASE', 'x')"),
        (
            "app",
            "SELECT safepay_admin_transition_deal("
            "gen_random_uuid(), 'REFUND', gen_random_uuid(), 'r', 'x')",
        ),
        (
            "app",
            "SELECT safepay__apply_transition("
            "gen_random_uuid(), 'FUND', 'BUYER', gen_random_uuid(), null, null, null)",
        ),
        (
            "system",
            f"SELECT {PUBLIC}(gen_random_uuid(), 'FUND', gen_random_uuid(), null, null, null)",
        ),
        (
            "system",
            "SELECT safepay_admin_set_user_status("
            "gen_random_uuid(), gen_random_uuid(), 'SUSPENDED', 'r')",
        ),
        (
            "admin",
            f"SELECT {PUBLIC}(gen_random_uuid(), 'FUND', gen_random_uuid(), null, null, null)",
        ),
        ("admin", f"SELECT {SYSTEM}(gen_random_uuid(), 'AUTO_RELEASE', 'x')"),
    ],
)
def test_cross_role_calls_denied(
    role: str, sql: str, app_engine: Engine, system_engine: Engine, admin_api_engine: Engine
) -> None:
    eng = {"app": app_engine, "system": system_engine, "admin": admin_api_engine}[role]
    with (
        eng.connect() as conn,
        pytest.raises(DBAPIError, match=r"permission denied|does not exist"),
    ):
        conn.execute(text(sql))


@pytest.mark.parametrize("role", ["app", "system", "admin"])
def test_no_runtime_role_can_grant_admin(
    role: str, app_engine: Engine, system_engine: Engine, admin_api_engine: Engine
) -> None:
    eng = {"app": app_engine, "system": system_engine, "admin": admin_api_engine}[role]
    with eng.connect() as conn, pytest.raises(DBAPIError, match="permission denied"):
        conn.execute(text("INSERT INTO admins (user_id, note) SELECT id, 'x' FROM users LIMIT 1"))


@pytest.mark.parametrize("role", ["system", "admin"])
def test_privileged_roles_cannot_write_money_tables(
    role: str, system_engine: Engine, admin_api_engine: Engine
) -> None:
    eng = system_engine if role == "system" else admin_api_engine
    for sql in (
        "UPDATE deals SET status = 'COMPLETED'",
        "INSERT INTO ledger_transactions (id, idempotency_key, kind) "
        "VALUES (gen_random_uuid(), 'x', 'X')",
        "DELETE FROM audit_events",
    ):
        with eng.connect() as conn, pytest.raises(DBAPIError, match="permission denied"):
            conn.execute(text(sql))


def test_system_function_rechecks_eligibility(app_engine: Engine, system_engine: Engine) -> None:
    """Even holding the worker credential, you cannot release before the window ends."""
    sc = new_deal(app_engine)
    advance_to_awaiting_payment(app_engine, sc)
    act(app_engine, sc, DealAction.FUND, Actor.BUYER)
    act(app_engine, sc, DealAction.MARK_DELIVERED, Actor.SELLER)
    with system_engine.connect() as conn, pytest.raises(DBAPIError, match="has not ended"):
        conn.execute(text(f"SELECT {SYSTEM}(:d, 'AUTO_RELEASE', 'x')"), {"d": sc.deal_id})
    with (
        system_engine.connect() as conn,
        pytest.raises(DBAPIError, match=r"not allowed|cannot|not yet|has not"),
    ):
        conn.execute(text(f"SELECT {SYSTEM}(:d, 'EXPIRE', 'x')"), {"d": sc.deal_id})


def _status(engine: Engine, deal_id: uuid.UUID) -> str:
    with engine.connect() as conn:
        return str(
            conn.execute(
                text("SELECT status FROM deals WHERE id = :d"), {"d": deal_id}
            ).scalar_one()
        )


def test_worker_expires_and_auto_releases_only_eligible_deals(
    app_engine: Engine, system_engine: Engine, engine: Engine
) -> None:
    stale = new_deal(app_engine)
    advance_to_awaiting_payment(app_engine, stale)
    fresh = new_deal(app_engine)
    advance_to_awaiting_payment(app_engine, fresh)
    delivered = new_deal(app_engine)
    advance_to_awaiting_payment(app_engine, delivered)
    act(app_engine, delivered, DealAction.FUND, Actor.BUYER)
    act(app_engine, delivered, DealAction.MARK_DELIVERED, Actor.SELLER)
    backdate(stale.deal_id, 8)
    backdate(delivered.deal_id, 4)  # default inspection window is 3 days
    result = run_once(system_engine)
    assert stale.deal_id in result.expired
    assert delivered.deal_id in result.released
    assert fresh.deal_id not in result.expired
    assert _status(engine, stale.deal_id) == DealStatus.EXPIRED
    assert _status(engine, fresh.deal_id) == DealStatus.AWAITING_PAYMENT
    assert _status(engine, delivered.deal_id) == DealStatus.COMPLETED
    # A second pass is a no-op.
    again = run_once(system_engine)
    assert stale.deal_id not in again.expired and delivered.deal_id not in again.released
