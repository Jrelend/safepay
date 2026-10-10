"""Beta v0.1 product scenarios A-L, end to end over HTTP on real PostgreSQL roles.

Every money movement here is SIMULATED. Scenario I is the key release-safety
check: an expired inspection window alone never releases escrow.
"""

import threading
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import URL, Engine, text

from app.worker import run_once
from tests.integration.web import (
    PASSWORD,
    Browser,
    admin_login,
    grant_admin,
    make_settings,
    new_deal_body,
    signup,
)

pytestmark = pytest.mark.usefixtures("fresh_rate_limits")
AMOUNT = "1250000"


@dataclass
class Cast:
    seller: Browser
    buyer: Browser
    stranger: Browser
    admin: Browser
    public: Any
    admin_settings: Any


@pytest.fixture
def cast(app_url: URL, admin_role_url: URL, engine: Engine) -> Cast:
    pub, adm = make_settings(app_url, "public"), make_settings(admin_role_url, "admin")
    seller, buyer, stranger, admin_user = (Browser(pub) for _ in range(4))
    signup(seller, engine, name="Худалдагч")
    signup(buyer, engine, name="Худалдан авагч")
    signup(stranger, engine, name="Гадны хүн")
    admin_email = signup(admin_user, engine, name="Админ")
    admin = admin_login(adm, engine, admin_email, grant_admin(engine, admin_email))
    return Cast(seller, buyer, stranger, admin, pub, adm)


def ok(r: Any) -> Any:
    assert r.status_code == 200, r.text
    return r.json()


def deal_until(c: Cast, stage: str) -> str:
    """Create a deal and advance it to AWAITING_PAYMENT / FUNDED / DELIVERED."""
    r = c.seller.post("/deals", json=new_deal_body())
    assert r.status_code == 201, r.text
    deal_id, token = r.json()["deal"]["id"], r.json()["invite_url"].rsplit("/", 1)[1]
    ok(c.buyer.post(f"/invites/{token}/join"))
    ok(c.seller.act(deal_id, "SUBMIT"))
    ok(c.buyer.act(deal_id, "ACCEPT"))
    if stage in ("FUNDED", "DELIVERED"):
        ok(c.buyer.act(deal_id, "FUND"))
    if stage == "DELIVERED":
        ok(c.seller.act(deal_id, "MARK_DELIVERED"))
    return str(deal_id)


def status(b: Browser, deal_id: str) -> str:
    return str(ok(b.get(f"/deals/{deal_id}"))["status"])


def balance(b: Browser) -> str:
    return str(ok(b.get("/me/wallet"))["balance_mnt"])


def settlements(engine: Engine, deal_id: str) -> list[str]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT kind FROM ledger_transactions WHERE deal_id = :d "
                    "AND kind IN ('ESCROW_RELEASE', 'ESCROW_REFUND')"
                ),
                {"d": deal_id},
            ).scalars()
        )


def open_dispute(c: Cast, deal_id: str, who: Browser, reason: str) -> str:
    deal = ok(who.act(deal_id, "OPEN_DISPUTE", note=reason))["deal"]
    assert deal["status"] == "DISPUTED"
    return str(deal["dispute_id"])


def test_a_buyer_and_seller_complete_a_transaction(cast: Cast, engine: Engine) -> None:
    deal_id = deal_until(cast, "DELIVERED")
    ok(cast.buyer.act(deal_id, "CONFIRM_RECEIPT"))
    assert status(cast.seller, deal_id) == "COMPLETED"
    assert balance(cast.seller) == AMOUNT
    assert settlements(engine, deal_id) == ["ESCROW_RELEASE"]


def test_b_buyer_disputes_before_confirming(cast: Cast, engine: Engine) -> None:
    deal_id = deal_until(cast, "DELIVERED")
    open_dispute(cast, deal_id, cast.buyer, "Бараа тайлбартай таарахгүй байна.")
    assert cast.buyer.act(deal_id, "CONFIRM_RECEIPT").status_code == 409
    assert cast.seller.act(deal_id, "REFUND").status_code == 409
    assert settlements(engine, deal_id) == []


def test_c_admin_resolves_with_simulated_refund(cast: Cast, engine: Engine) -> None:
    deal_id = deal_until(cast, "DELIVERED")
    dispute_id = open_dispute(cast, deal_id, cast.buyer, "Эвдэрсэн ирсэн.")
    r = cast.admin.post(
        f"/admin/disputes/{dispute_id}/decision",
        json={"outcome": "REFUND_TO_BUYER", "reason": "Гэмтлийг зургаар нотолсон."},
    )
    assert ok(r)["deal_status"] == "REFUNDED"
    assert balance(cast.buyer) == AMOUNT and balance(cast.seller) == "0"
    assert settlements(engine, deal_id) == ["ESCROW_REFUND"]


def test_d_admin_resolves_with_simulated_release(cast: Cast, engine: Engine) -> None:
    deal_id = deal_until(cast, "DELIVERED")
    dispute_id = open_dispute(cast, deal_id, cast.buyer, "Хүргэлт хоцорсон.")
    r = cast.admin.post(
        f"/admin/disputes/{dispute_id}/decision",
        json={"outcome": "RELEASE_TO_SELLER", "reason": "Бараа бүрэн, хугацаандаа хүргэгдсэн."},
    )
    assert ok(r)["deal_status"] == "COMPLETED"
    assert balance(cast.seller) == AMOUNT and balance(cast.buyer) == "0"
    assert settlements(engine, deal_id) == ["ESCROW_RELEASE"]


def test_e_conflicting_actions_at_the_same_time(cast: Cast, engine: Engine) -> None:
    deal_id = deal_until(cast, "DELIVERED")
    barrier = threading.Barrier(2)
    codes: dict[str, int] = {}

    def run(name: str, b: Browser, action: str, **kw: Any) -> None:
        barrier.wait()
        codes[name] = b.act(deal_id, action, **kw).status_code

    threads = [
        threading.Thread(target=run, args=("confirm", cast.buyer, "CONFIRM_RECEIPT")),
        threading.Thread(target=run, args=("refund", cast.seller, "REFUND")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(codes.values()) == [200, 409], codes
    assert len(settlements(engine, deal_id)) == 1


def test_f_unauthorized_user_cannot_view_another_deal(cast: Cast) -> None:
    deal_id = deal_until(cast, "FUNDED")
    for path in ("", "/timeline", "/escrow"):
        assert cast.stranger.get(f"/deals/{deal_id}{path}").status_code == 404
    assert cast.stranger.act(deal_id, "CONFIRM_RECEIPT").status_code == 404


def test_g_duplicate_funding(cast: Cast, engine: Engine) -> None:
    deal_id = deal_until(cast, "AWAITING_PAYMENT")
    first = ok(cast.buyer.act(deal_id, "FUND", key="fund-twice"))
    replay = ok(cast.buyer.act(deal_id, "FUND", key="fund-twice"))
    assert replay["replayed"] is True
    assert replay["ledger_transaction_id"] == first["ledger_transaction_id"]
    assert cast.buyer.act(deal_id, "FUND").status_code == 409  # new key, already funded
    with engine.connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM ledger_transactions "
                    "WHERE deal_id = :d AND kind = 'ESCROW_HOLD'"
                ),
                {"d": deal_id},
            ).scalar_one()
            == 1
        )


def _expire_inspection(engine: Engine, deal_id: str) -> None:
    with engine.begin() as conn:  # test-only time travel (superuser, triggers bypassed)
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(
            text("UPDATE deals SET status_changed_at = status_changed_at - :d WHERE id = :id"),
            {"d": timedelta(days=30), "id": deal_id},
        )


def test_h_buyer_refuses_to_confirm_seller_escalates(
    cast: Cast, admin_engine: Engine, system_engine: Engine, engine: Engine
) -> None:
    deal_id = deal_until(cast, "DELIVERED")
    _expire_inspection(admin_engine, deal_id)
    run_once(system_engine)
    assert status(cast.seller, deal_id) == "DELIVERED"  # funds still held
    view = ok(cast.seller.get(f"/deals/{deal_id}"))
    assert "OPEN_DISPUTE" in view["actions"] and "CONFIRM_RECEIPT" not in view["actions"]
    dispute_id = open_dispute(cast, deal_id, cast.seller, "Худалдан авагч хариу өгөхгүй байна.")
    ok(
        cast.admin.post(
            f"/admin/disputes/{dispute_id}/decision",
            json={"outcome": "RELEASE_TO_SELLER", "reason": "Хүргэлтийн баримт бүрэн байна."},
        )
    )
    assert balance(cast.seller) == AMOUNT


def test_i_inspection_period_expires_without_buyer_action(
    cast: Cast, admin_engine: Engine, system_engine: Engine, engine: Engine
) -> None:
    """No simulated funds move merely because the inspection period expired."""
    deal_id = deal_until(cast, "DELIVERED")
    _expire_inspection(admin_engine, deal_id)
    for _ in range(3):
        result = run_once(system_engine)
        assert result.released == []
    view = ok(cast.buyer.get(f"/deals/{deal_id}"))
    assert view["status"] == "DELIVERED"
    assert view["auto_release_at"] is None and view["inspection_ends_at"]
    assert settlements(engine, deal_id) == []
    assert balance(cast.seller) == "0"
    # The buyer can still confirm late, which is what releases the money.
    ok(cast.buyer.act(deal_id, "CONFIRM_RECEIPT"))
    assert balance(cast.seller) == AMOUNT


def test_j_suspended_account_cannot_take_financial_actions(cast: Cast, engine: Engine) -> None:
    deal_id = deal_until(cast, "AWAITING_PAYMENT")
    with engine.connect() as conn:
        buyer_id = conn.execute(
            text("SELECT user_id FROM deal_participants WHERE deal_id = :d AND role = 'BUYER'"),
            {"d": deal_id},
        ).scalar_one()
    r = cast.admin.post(
        f"/admin/users/{buyer_id}/status", json={"status": "SUSPENDED", "reason": "fraud check"}
    )
    assert r.status_code == 204, r.text
    # Existing session is gone, re-login refused, and the DB itself refuses the actor.
    assert cast.buyer.act(deal_id, "FUND").status_code == 401
    with engine.connect() as conn:
        email = conn.execute(
            text("SELECT email FROM users WHERE id = :u"), {"u": buyer_id}
        ).scalar_one()
    again = Browser(cast.public)
    assert again.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 403
    assert settlements(engine, deal_id) == []
    assert status(cast.seller, deal_id) == "AWAITING_PAYMENT"


def test_k_user_tries_admin_functionality(cast: Cast) -> None:
    # Public API has no admin routes; the admin API ignores public sessions.
    assert cast.buyer.get("/admin/overview").status_code == 404
    impostor = Browser(cast.admin_settings)
    impostor.client.cookies.update(dict(cast.buyer.client.cookies))
    assert impostor.get("/admin/overview").status_code == 401
    assert impostor.get("/admin/users").status_code == 401


# Scenario L (database/API temporarily unavailable) is tested without a database:
# tests/unit/test_runtime_safety.py::test_database_outage_returns_clean_503 (API -> 503)
# and apps/web/src/lib/proxy.ts (web proxy -> 502 upstream_unavailable).
