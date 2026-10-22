"""LOCAL_DEMO over real HTTP + PostgreSQL roles (see app/local_demo.py).

The seeded buyer starts with simulated money that moves into escrow when a demo
deal is funded, and back out on refund or release. Everything is gated by the API
setting (``LOCAL_DEMO``, local/test only) and the owner-only database policy set by
``demo-seed``; non-demo deals, and every deal while the policy is off, are funded
from SIMULATED_CASH exactly as before.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import URL, Engine, text

from app import cli, local_demo
from app.core.config import Settings
from tests.integration.web import PASSWORD, Browser, make_settings, new_deal_body, signup

pytestmark = pytest.mark.usefixtures("fresh_rate_limits")
AMOUNT = 1_250_000


def ok(r: Any) -> Any:
    assert r.status_code in (200, 201, 202), r.text
    return r.json()


def set_wallet_policy(owner: Engine, enabled: bool) -> None:
    with owner.begin() as conn:
        conn.execute(
            text("UPDATE platform_policy SET demo_wallets_enabled = :e WHERE id"), {"e": enabled}
        )


@pytest.fixture
def seeded(engine: Engine) -> Iterator[None]:
    """``demo-seed`` as the owner; afterwards the policy goes back off so other tests'
    demo deals (BETA_DEMO_MODE accounts, empty wallets) keep using SIMULATED_CASH."""
    with engine.begin() as conn:
        local_demo.seed(conn)
    yield
    set_wallet_policy(engine, False)


@pytest.fixture
def demo_settings(app_url: URL) -> Settings:
    return make_settings(app_url, "public", local_demo=True)


def persona(settings: Settings, p: local_demo.Persona) -> Browser:
    b = Browser(settings)
    ok(b.post("/auth/login", json={"email": p.email, "password": local_demo.DEMO_PASSWORD}))
    return b


def balance(b: Browser) -> int:
    return int(ok(b.get("/me/wallet"))["balance_mnt"])


def agreed(buyer: Browser, seller: Browser, amount: int = AMOUNT) -> str:
    """The buyer creates the deal naming the seeded seller, who is attached at once."""
    created = ok(
        buyer.post(
            "/deals",
            json=new_deal_body(
                "BUYER", amount_mnt=amount, counterparty_email=local_demo.SELLER.email
            ),
        )
    )
    deal_id = str(created["deal"]["id"])
    assert ok(seller.get(f"/deals/{deal_id}"))["my_role"] == "SELLER"
    ok(buyer.act(deal_id, "SUBMIT"))
    assert ok(seller.act(deal_id, "ACCEPT"))["deal"]["status"] == "AWAITING_PAYMENT"
    return deal_id


def escrow_held(b: Browser, deal_id: str) -> int:
    held = 0
    for p in ok(b.get(f"/deals/{deal_id}/escrow")):
        held += int(p["amount_mnt"]) * (1 if p["kind"] == "ESCROW_HOLD" else -1)
    return held


# ------------------------------------------------------------------------ seeding


def test_seed_is_idempotent_and_funds_only_the_buyer(engine: Engine, seeded: None) -> None:
    with engine.begin() as conn:
        local_demo.seed(conn)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT u.email, u.is_demo, u.email_verified_at IS NOT NULL, "
                "EXISTS (SELECT FROM admins a WHERE a.user_id = u.id) "
                "FROM users u WHERE u.email = ANY(:e) ORDER BY u.email"
            ),
            {"e": sorted(local_demo.PERSONA_EMAILS)},
        ).all()
        topups = conn.execute(
            text("SELECT count(*) FROM ledger_transactions WHERE kind = 'DEMO_TOPUP'")
        ).scalar_one()
        policy = conn.execute(
            text("SELECT demo_wallets_enabled FROM platform_policy WHERE id")
        ).scalar_one()
    assert [tuple(r) for r in rows] == [
        (local_demo.ADMIN.email, False, True, True),
        (local_demo.BUYER.email, True, True, False),
        (local_demo.SELLER.email, True, True, False),
    ]
    assert topups == 1
    assert policy is True


def test_demo_seed_cli_refuses_outside_local(monkeypatch: pytest.MonkeyPatch) -> None:
    staging = Settings(
        app_env="staging",
        public_web_url="https://safepay.example",
        cors_allowed_origins=["https://safepay.example"],
    )
    monkeypatch.setattr(cli, "get_settings", lambda: staging)
    with pytest.raises(SystemExit, match="local demos only"):
        cli.demo_seed()


# ---------------------------------------------------------------------- workflows


def test_payment_moves_buyer_money_into_escrow_and_release_pays_seller(
    demo_settings: Settings, seeded: None
) -> None:
    buyer = persona(demo_settings, local_demo.BUYER)
    seller = persona(demo_settings, local_demo.SELLER)
    deal_id = agreed(buyer, seller)
    start_buyer, start_seller = balance(buyer), balance(seller)

    ok(buyer.act(deal_id, "FUND"))
    assert balance(buyer) == start_buyer - AMOUNT
    assert escrow_held(buyer, deal_id) == AMOUNT
    ok(seller.act(deal_id, "MARK_DELIVERED"))
    assert ok(buyer.act(deal_id, "CONFIRM_RECEIPT"))["deal"]["status"] == "COMPLETED"
    assert escrow_held(buyer, deal_id) == 0
    assert (balance(buyer), balance(seller)) == (start_buyer - AMOUNT, start_seller + AMOUNT)


def test_refund_returns_money_to_the_buyer_wallet(demo_settings: Settings, seeded: None) -> None:
    buyer = persona(demo_settings, local_demo.BUYER)
    seller = persona(demo_settings, local_demo.SELLER)
    deal_id = agreed(buyer, seller)
    start = balance(buyer)
    ok(buyer.act(deal_id, "FUND"))
    assert balance(buyer) == start - AMOUNT
    assert ok(seller.act(deal_id, "REFUND", note="Бараа дууссан"))["deal"]["status"] == "REFUNDED"
    assert balance(buyer) == start


def test_cancel_before_payment_moves_no_money(demo_settings: Settings, seeded: None) -> None:
    buyer = persona(demo_settings, local_demo.BUYER)
    seller = persona(demo_settings, local_demo.SELLER)
    deal_id = agreed(buyer, seller)
    start = balance(buyer)
    ok(buyer.act(deal_id, "CANCEL", note="Өөр худалдагч олдлоо"))
    assert balance(buyer) == start


def test_demo_admin_resolves_a_dispute_with_the_demo_code(
    demo_settings: Settings, admin_role_url: URL, seeded: None
) -> None:
    buyer = persona(demo_settings, local_demo.BUYER)
    seller = persona(demo_settings, local_demo.SELLER)
    deal_id = agreed(buyer, seller)
    start_buyer = balance(buyer)
    ok(buyer.act(deal_id, "FUND"))
    ok(seller.act(deal_id, "MARK_DELIVERED"))
    dispute_id = ok(buyer.act(deal_id, "OPEN_DISPUTE", note="Дэлгэц хагарсан"))["deal"][
        "dispute_id"
    ]

    admin = Browser(make_settings(admin_role_url, "admin", local_demo=True))
    code = ok(buyer.get("/demo/admin-code"))["code"]
    ok(
        admin.post(
            "/admin/auth/login",
            json={
                "email": local_demo.ADMIN.email,
                "password": local_demo.DEMO_ADMIN_PASSWORD,
                "code": code,
            },
        )
    )
    # The same code cannot be replayed; the next step's code is still accepted.
    second = Browser(make_settings(admin_role_url, "admin", local_demo=True))
    login = {"email": local_demo.ADMIN.email, "password": local_demo.DEMO_ADMIN_PASSWORD}
    assert second.post("/admin/auth/login", json={**login, "code": code}).status_code == 401
    ahead = ok(buyer.get("/demo/admin-code", params={"ahead": 1}))["code"]
    ok(second.post("/admin/auth/login", json={**login, "code": ahead}))

    out = ok(
        admin.post(
            f"/admin/disputes/{dispute_id}/decision",
            json={"outcome": "REFUND_TO_BUYER", "reason": "Худалдагч нотолгоо өгсөнгүй"},
        )
    )
    assert out["deal_status"] == "REFUNDED"
    assert balance(buyer) == start_buyer


def test_payment_beyond_the_demo_balance_is_refused(demo_settings: Settings, seeded: None) -> None:
    buyer = persona(demo_settings, local_demo.BUYER)
    seller = persona(demo_settings, local_demo.SELLER)
    deal_id = agreed(buyer, seller, amount=balance(buyer) + 1)
    start = balance(buyer)
    r = buyer.act(deal_id, "FUND")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "insufficient_demo_balance"
    assert ok(buyer.get(f"/deals/{deal_id}"))["status"] == "AWAITING_PAYMENT"
    assert balance(buyer) == start


# ------------------------------------------------------------------- isolation


def test_non_demo_deals_are_still_funded_from_simulated_cash(
    app_url: URL, engine: Engine, seeded: None
) -> None:
    normal = make_settings(app_url, "public", local_demo=True)
    seller, buyer = Browser(normal), Browser(normal)
    # Local demo: no verification email, the accounts are verified at registration.
    signup(seller, engine, name="Болд", verify=False)
    signup(buyer, engine, name="Номин", verify=False)
    created = ok(seller.post("/deals", json=new_deal_body(amount_mnt=AMOUNT)))
    deal_id = created["deal"]["id"]
    assert created["deal"]["is_demo"] is False
    ok(buyer.post(f"/invites/{created['invite_url'].rsplit('/', 1)[1]}/join"))
    ok(seller.act(deal_id, "SUBMIT"))
    ok(buyer.act(deal_id, "ACCEPT"))
    ok(buyer.act(deal_id, "FUND"))  # an empty wallet is no obstacle: SIMULATED_CASH pays
    assert balance(buyer) == 0
    with engine.connect() as conn:
        debited = conn.execute(
            text(
                "SELECT a.purpose FROM ledger_entries e "
                "JOIN ledger_transactions t ON t.id = e.transaction_id "
                "JOIN ledger_accounts a ON a.id = e.account_id "
                "WHERE t.deal_id = :d AND t.kind = 'ESCROW_HOLD' AND e.direction = 'DEBIT'"
            ),
            {"d": uuid.UUID(str(deal_id))},
        ).scalar_one()
    assert debited == "SIMULATED_CASH"


def test_policy_off_funds_demo_deals_from_simulated_cash(
    demo_settings: Settings, engine: Engine, seeded: None
) -> None:
    buyer = persona(demo_settings, local_demo.BUYER)
    seller = persona(demo_settings, local_demo.SELLER)
    deal_id = agreed(buyer, seller)
    set_wallet_policy(engine, False)
    start = balance(buyer)
    ok(buyer.act(deal_id, "FUND"))
    assert balance(buyer) == start


def test_demo_routes_and_shortcuts_exist_only_in_local_demo(
    app_url: URL, engine: Engine, seeded: None
) -> None:
    plain = make_settings(app_url, "public")
    b = Browser(plain)
    assert b.get("/demo/accounts").status_code == 404
    assert b.get("/demo/admin-code").status_code == 404
    # Without LOCAL_DEMO a seeded counterparty is NOT attached automatically.
    buyer = persona(plain, local_demo.BUYER)
    created = ok(
        buyer.post(
            "/deals",
            json=new_deal_body("BUYER", counterparty_email=local_demo.SELLER.email),
        )
    )
    assert created["deal"]["counterparty_name"] is None

    demo = Browser(make_settings(app_url, "public", local_demo=True))
    accounts = {a["key"]: a for a in ok(demo.get("/demo/accounts"))}
    assert set(accounts) == {"buyer", "seller", "admin"}
    assert accounts["buyer"]["email"] == local_demo.BUYER.email


def test_login_limits_lifted_only_for_seeded_accounts_in_local_demo(
    app_url: URL, demo_settings: Settings, seeded: None
) -> None:
    body = {"email": local_demo.SELLER.email, "password": "wrong-password-123"}
    demo = Browser(demo_settings)
    assert {demo.post("/auth/login", json=body).status_code for _ in range(12)} == {401}

    plain = Browser(make_settings(app_url, "public"))
    codes = [plain.post("/auth/login", json=body).status_code for _ in range(12)]
    assert 429 in codes

    stranger = {"email": "not-a-demo@example.com", "password": "wrong-password-123"}
    codes = [demo.post("/auth/login", json=stranger).status_code for _ in range(12)]
    assert 429 in codes


# ------------------------------------------------------------ email verification


def outbox(owner: Engine, email: str) -> list[str]:
    with owner.connect() as conn:
        return list(
            conn.execute(
                text("SELECT template FROM email_outbox WHERE to_email = :e"), {"e": email}
            ).scalars()
        )


def test_local_demo_registration_needs_no_email_verification(
    demo_settings: Settings, app_url: URL, engine: Engine
) -> None:
    seller, buyer = Browser(demo_settings), Browser(demo_settings)
    emails = []
    for b, name in ((seller, "Болд"), (buyer, "Номин")):
        email = f"local-{uuid.uuid4().hex[:8]}@example.com"
        body = {"email": email, "password": PASSWORD, "display_name": name}
        assert ok(b.post("/auth/register", json=body))["verification_required"] is False
        me = ok(b.post("/auth/login", json={"email": email, "password": PASSWORD}))
        assert me["email_verified"] is True and me["can_transact"] is True
        assert outbox(engine, email) == []  # no verification email or link
        emails.append(email)
    # Registering an existing address sends nothing either.
    again = {"email": emails[0], "password": PASSWORD, "display_name": "Болд"}
    assert seller.post("/auth/register", json=again).status_code == 202
    assert outbox(engine, emails[0]) == []

    # The whole escrow workflow, without ever opening an inbox.
    created = ok(seller.post("/deals", json=new_deal_body(amount_mnt=AMOUNT)))
    deal_id = created["deal"]["id"]
    ok(buyer.post(f"/invites/{created['invite_url'].rsplit('/', 1)[1]}/join"))
    ok(seller.act(deal_id, "SUBMIT"))
    ok(buyer.act(deal_id, "ACCEPT"))
    ok(buyer.act(deal_id, "FUND"))
    ok(seller.act(deal_id, "MARK_DELIVERED"))
    assert ok(buyer.act(deal_id, "CONFIRM_RECEIPT"))["deal"]["status"] == "COMPLETED"
    assert balance(seller) == AMOUNT


def test_registration_outside_local_demo_still_requires_verification(
    app_url: URL, engine: Engine
) -> None:
    b = Browser(make_settings(app_url, "public"))
    email = f"plain-{uuid.uuid4().hex[:8]}@example.com"
    body = {"email": email, "password": PASSWORD, "display_name": "Бат"}
    assert ok(b.post("/auth/register", json=body))["verification_required"] is True
    me = ok(b.post("/auth/login", json={"email": email, "password": PASSWORD}))
    assert me["email_verified"] is False and me["can_transact"] is False
    assert outbox(engine, email) == ["verify_email"]


def test_seed_verifies_accounts_left_unverified(app_url: URL, engine: Engine) -> None:
    b = Browser(make_settings(app_url, "public"))
    email = f"stuck-{uuid.uuid4().hex[:8]}@example.com"
    body = {"email": email, "password": PASSWORD, "display_name": "Туяа"}
    assert ok(b.post("/auth/register", json=body))["verification_required"] is True
    with engine.begin() as conn:
        local_demo.seed(conn)
    try:
        me = ok(b.post("/auth/login", json={"email": email, "password": PASSWORD}))
        assert me["email_verified"] is True
    finally:
        set_wallet_policy(engine, False)
