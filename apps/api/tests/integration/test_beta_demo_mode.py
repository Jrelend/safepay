"""BETA_DEMO_MODE over real HTTP + PostgreSQL roles.

Demo accounts (registered while the mode is on) use every deal workflow without
email verification; everything else about authentication, authorization, CSRF,
rate limits and the simulated ledger is unchanged. Demo and non-demo accounts
never share a deal, enforced by the API and again by the database.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import URL, Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models import Deal, ParticipantRole
from tests.integration.conftest import add_participant, make_user
from tests.integration.web import (
    PASSWORD,
    Browser,
    admin_login,
    grant_admin,
    make_settings,
    new_deal_body,
    signup,
    user_id,
)

pytestmark = pytest.mark.usefixtures("fresh_rate_limits", "demo_policy")
AMOUNT = 1_250_000


def set_policy(owner: Engine, enabled: bool) -> None:
    with owner.begin() as conn:
        conn.execute(
            text("UPDATE platform_policy SET beta_demo_enabled = :e WHERE id"), {"e": enabled}
        )


@pytest.fixture
def demo_policy(engine: Engine) -> Iterator[None]:
    """The database side of BETA_DEMO_MODE (owner-only), on for these tests."""
    set_policy(engine, True)
    yield
    set_policy(engine, False)


@dataclass
class Party:
    browser: Browser
    email: str


def ok(r: Any) -> Any:
    assert r.status_code in (200, 201), r.text
    return r.json()


@pytest.fixture
def demo(app_url: URL) -> Any:
    settings = make_settings(app_url, "public", beta_demo_mode=True)
    return lambda: Browser(settings)


@pytest.fixture
def normal(app_url: URL) -> Any:
    settings = make_settings(app_url, "public")
    return lambda: Browser(settings)


def demo_user(new: Any, engine: Engine, name: str) -> Party:
    """Register and sign in WITHOUT verifying the email address."""
    b = new()
    return Party(b, signup(b, engine, name=name, verify=False))


@pytest.fixture
def seller(demo: Any, engine: Engine) -> Party:
    return demo_user(demo, engine, "Демо худалдагч")


@pytest.fixture
def buyer(demo: Any, engine: Engine) -> Party:
    return demo_user(demo, engine, "Демо худалдан авагч")


def agreed(seller: Party, buyer: Party) -> str:
    """Seller creates, buyer joins, terms submitted and accepted: AWAITING_PAYMENT."""
    created = ok(seller.browser.post("/deals", json=new_deal_body(amount_mnt=AMOUNT)))
    deal_id = created["deal"]["id"]
    ok(buyer.browser.post(f"/invites/{created['invite_url'].rsplit('/', 1)[1]}/join"))
    ok(seller.browser.act(deal_id, "SUBMIT"))
    assert ok(buyer.browser.act(deal_id, "ACCEPT"))["deal"]["status"] == "AWAITING_PAYMENT"
    return str(deal_id)


def balance(p: Party) -> int:
    return int(ok(p.browser.get("/me/wallet"))["balance_mnt"])


def status(p: Party, deal_id: str) -> str:
    return str(ok(p.browser.get(f"/deals/{deal_id}"))["status"])


# --------------------------------------------------------------------------- lifecycle


def test_demo_registration_needs_no_verification(demo: Any, engine: Engine) -> None:
    b = demo()
    email = "demo-reg-" + PASSWORD[:3].lower() + "@example.com"
    r = b.post("/auth/register", json={"email": email, "password": PASSWORD, "display_name": "Д"})
    assert r.status_code == 422  # display_name still validated (min length 2)
    body = {"email": email, "password": PASSWORD, "display_name": "Дулам"}
    r = b.post("/auth/register", json=body)
    assert r.json() == {"status": "accepted", "verification_required": False}
    ok(b.post("/auth/login", json={"email": email, "password": PASSWORD}))
    me = ok(b.get("/auth/me"))
    assert (me["email_verified"], me["is_demo"], me["can_transact"]) == (False, True, True)


def test_two_demo_users_complete_a_deal(seller: Party, buyer: Party, engine: Engine) -> None:
    deal_id = agreed(seller, buyer)
    deal = ok(buyer.browser.act(deal_id, "FUND"))["deal"]
    assert deal["status"] == "FUNDED" and deal["is_demo"] is True
    ok(seller.browser.act(deal_id, "MARK_DELIVERED"))
    assert ok(buyer.browser.act(deal_id, "CONFIRM_RECEIPT"))["deal"]["status"] == "COMPLETED"
    assert (balance(seller), balance(buyer)) == (AMOUNT, 0)
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT is_demo FROM deals WHERE id = :d"), {"d": deal_id}
        ).scalar_one()


@pytest.mark.parametrize("who", ["seller", "buyer"])
def test_demo_cancellation_before_payment(seller: Party, buyer: Party, who: str) -> None:
    deal_id = agreed(seller, buyer)
    canceller = seller if who == "seller" else buyer
    assert ok(canceller.browser.act(deal_id, "CANCEL"))["deal"]["status"] == "CANCELLED"
    assert ok(seller.browser.get(f"/deals/{deal_id}/escrow")) == []
    assert (balance(seller), balance(buyer)) == (0, 0)


def test_demo_decline_terms(seller: Party, buyer: Party) -> None:
    created = ok(seller.browser.post("/deals", json=new_deal_body(amount_mnt=AMOUNT)))
    deal_id = created["deal"]["id"]
    ok(buyer.browser.post(f"/invites/{created['invite_url'].rsplit('/', 1)[1]}/join"))
    ok(seller.browser.act(deal_id, "SUBMIT"))
    assert ok(buyer.browser.act(deal_id, "DECLINE"))["deal"]["status"] == "CANCELLED"


@pytest.mark.parametrize("after_delivery", [False, True])
def test_demo_seller_refund(seller: Party, buyer: Party, after_delivery: bool) -> None:
    deal_id = agreed(seller, buyer)
    ok(buyer.browser.act(deal_id, "FUND"))
    if after_delivery:
        ok(seller.browser.act(deal_id, "MARK_DELIVERED"))
    assert ok(seller.browser.act(deal_id, "REFUND"))["deal"]["status"] == "REFUNDED"
    assert (balance(seller), balance(buyer)) == (0, AMOUNT)


@pytest.mark.parametrize(
    ("outcome", "final", "seller_gets"),
    [("REFUND_TO_BUYER", "REFUNDED", 0), ("RELEASE_TO_SELLER", "COMPLETED", AMOUNT)],
)
def test_demo_dispute_resolved_by_admin(
    seller: Party,
    buyer: Party,
    normal: Any,
    admin_role_url: URL,
    engine: Engine,
    outcome: str,
    final: str,
    seller_gets: int,
) -> None:
    deal_id = agreed(seller, buyer)
    ok(buyer.browser.act(deal_id, "FUND"))
    ok(seller.browser.act(deal_id, "MARK_DELIVERED"))
    dispute_id = ok(buyer.browser.act(deal_id, "OPEN_DISPUTE", note="Бараа эвдэрсэн ирсэн"))[
        "deal"
    ]["dispute_id"]
    ok(seller.browser.post(f"/disputes/{dispute_id}/statements", json={"body": "Бүрэн бүтэн"}))
    # Demo parties cannot decide their own dispute; only the admin API can.
    assert buyer.browser.post(f"/admin/disputes/{dispute_id}/decision", json={}).status_code == 404
    assert buyer.browser.act(deal_id, "RESOLVE_REFUND").status_code in (403, 409, 422)

    admin_email = signup(normal(), engine, name="Админ")
    secret = grant_admin(engine, admin_email)
    admin = admin_login(make_settings(admin_role_url, "admin"), engine, admin_email, secret)
    out = ok(
        admin.post(
            f"/admin/disputes/{dispute_id}/decision",
            json={"outcome": outcome, "reason": "Хоёр талын нотлох баримтыг шалгав"},
        )
    )
    assert out["deal_status"] == final
    assert (balance(seller), balance(buyer)) == (seller_gets, AMOUNT - seller_gets)
    demo_admin_view = ok(admin.get("/admin/users"))
    flags = {u["email"]: u["is_demo"] for u in demo_admin_view}
    assert flags[seller.email] is True and flags[admin_email] is False


# --------------------------------------------------------- verification policy unchanged


def test_without_demo_mode_verification_is_still_required(normal: Any, engine: Engine) -> None:
    b = normal()
    r = b.post(
        "/auth/register",
        json={"email": "plain-unverified@example.com", "password": PASSWORD, "display_name": "Б"},
    )
    assert r.status_code == 422
    email = signup(b, engine, verify=False)
    me = ok(b.get("/auth/me"))
    assert (me["is_demo"], me["can_transact"]) == (False, False)
    r = b.post("/deals", json=new_deal_body())
    assert r.status_code == 403 and r.json()["error"]["code"] == "email_not_verified"
    # ...and turning demo mode on does not exempt accounts registered without it.
    later = Browser(make_settings_like(b, beta_demo_mode=True))
    ok(later.post("/auth/login", json={"email": email, "password": PASSWORD}))
    assert later.post("/deals", json=new_deal_body()).status_code == 403


def make_settings_like(b: Browser, **extra: Any) -> Any:
    return b.app.state.settings.model_copy(update=extra)


def test_client_cannot_ask_for_a_demo_account(normal: Any, engine: Engine) -> None:
    b = normal()
    email = "wants-demo@example.com"
    r = b.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "display_name": "Бат", "is_demo": True},
    )
    assert r.json() == {"status": "accepted", "verification_required": True}
    with engine.connect() as conn:
        assert not conn.execute(
            text("SELECT is_demo FROM users WHERE email = :e"), {"e": email}
        ).scalar_one()


def test_turning_demo_mode_off_suspends_unverified_demo_accounts(
    seller: Party, buyer: Party, normal: Any
) -> None:
    deal_id = agreed(seller, buyer)
    off = normal()
    ok(off.post("/auth/login", json={"email": buyer.email, "password": PASSWORD}))
    me = ok(off.get("/auth/me"))
    assert (me["is_demo"], me["can_transact"]) == (True, False)
    r = off.act(deal_id, "FUND")
    assert r.status_code == 403 and r.json()["error"]["code"] == "email_not_verified"
    # Reading their own deals still works; nothing moved.
    assert ok(off.get(f"/deals/{deal_id}"))["status"] == "AWAITING_PAYMENT"


# ----------------------------------------------------------------- data separation


def test_demo_and_real_accounts_never_share_a_deal(
    seller: Party, normal: Any, demo: Any, engine: Engine
) -> None:
    real = Party(normal(), "")
    real.email = signup(real.browser, engine, name="Жинхэнэ")
    # Real deal, demo joiner.
    created = ok(real.browser.post("/deals", json=new_deal_body()))
    assert created["deal"]["is_demo"] is False
    token = created["invite_url"].rsplit("/", 1)[1]
    preview, join = (
        seller.browser.get(f"/invites/{token}"),
        seller.browser.post(f"/invites/{token}/join"),
    )
    for r in (preview, join):
        assert r.status_code == 403 and r.json()["error"]["code"] == "demo_mismatch"
    # Demo deal, real joiner (even a verified one, on a demo-mode server).
    created = ok(seller.browser.post("/deals", json=new_deal_body()))
    token = created["invite_url"].rsplit("/", 1)[1]
    on = demo()
    ok(on.post("/auth/login", json={"email": real.email, "password": PASSWORD}))
    r = on.post(f"/invites/{token}/join")
    assert r.status_code == 403 and r.json()["error"]["code"] == "demo_mismatch"


def test_database_enforces_the_partition(
    seller: Party, normal: Any, engine: Engine, app_engine: Engine
) -> None:
    real_email = signup(normal(), engine, name="Жинхэнэ")
    real_id, demo_id = user_id(engine, real_email), user_id(engine, seller.email)
    demo_deal = ok(seller.browser.post("/deals", json=new_deal_body()))["deal"]["id"]

    def refused(sql: str, params: dict[str, Any], expected: str) -> None:
        with pytest.raises(DBAPIError, match=expected), app_engine.begin() as conn:
            conn.execute(text(sql), params)

    # The runtime role cannot flip the flag on users or deals.
    refused("UPDATE users SET is_demo = false WHERE id = :u", {"u": demo_id}, "permission denied")
    refused("UPDATE deals SET is_demo = false WHERE id = :d", {"d": demo_deal}, "permission denied")
    # Nor insert a mixed participant or a deal flagged differently from its creator.
    refused(
        "INSERT INTO deal_participants (id, deal_id, user_id, role) "
        "VALUES (gen_random_uuid(), :d, :u, 'BUYER')",
        {"d": demo_deal, "u": real_id},
        "cannot share a deal",
    )
    refused(
        "INSERT INTO deals (id, reference, title, amount_mnt, created_by_id, invite_token_hash, "
        "is_demo) VALUES (gen_random_uuid(), 'SP-DEMOX1', 't', 1000, :u, :h, true)",
        {"u": real_id, "h": "f" * 64},
        "creator is a demo account",
    )


# --------------------------------------------- authorization and balance audit (demo)


@pytest.fixture
def stranger(demo: Any, engine: Engine) -> Party:
    return demo_user(demo, engine, "Гадны хүн")


def test_demo_strangers_cannot_see_or_touch_other_deals(
    seller: Party, buyer: Party, stranger: Party
) -> None:
    deal_id = agreed(seller, buyer)
    ok(buyer.browser.act(deal_id, "FUND"))
    for path in ("", "/timeline", "/escrow"):
        assert stranger.browser.get(f"/deals/{deal_id}{path}").status_code == 404
    for action in ("MARK_DELIVERED", "REFUND", "CONFIRM_RECEIPT", "OPEN_DISPUTE", "CANCEL"):
        assert stranger.browser.act(deal_id, action, note="x" * 10).status_code == 404
    assert deal_id not in {d["id"] for d in ok(stranger.browser.get("/deals"))}
    assert status(seller, deal_id) == "FUNDED"


@pytest.mark.parametrize(
    ("actor", "action"),
    [
        ("seller", "FUND"),  # only the buyer pays
        ("buyer", "MARK_DELIVERED"),  # only the seller delivers
        ("buyer", "REFUND"),  # the buyer cannot pull money back alone
        ("buyer", "CONFIRM_RECEIPT"),  # not before delivery
        ("seller", "CONFIRM_RECEIPT"),  # the seller cannot release to themselves
        ("seller", "AUTO_RELEASE"),  # system-only
        ("buyer", "RESOLVE_REFUND"),  # admin-only
        ("seller", "RESOLVE_RELEASE"),  # admin-only
    ],
)
def test_demo_parties_cannot_take_the_other_role(
    seller: Party, buyer: Party, actor: str, action: str
) -> None:
    deal_id = agreed(seller, buyer)
    if action != "FUND":
        ok(buyer.browser.act(deal_id, "FUND"))
    before = status(seller, deal_id)
    party = seller if actor == "seller" else buyer
    r = party.browser.act(deal_id, action)
    assert r.status_code in (403, 409, 422), r.text
    assert status(seller, deal_id) == before
    assert (balance(seller), balance(buyer)) == (0, 0)


def test_demo_balance_cannot_be_manipulated(seller: Party, buyer: Party, engine: Engine) -> None:
    deal_id = agreed(seller, buyer)
    # Terms (and so the amount) are frozen once accepted.
    version = ok(seller.browser.get(f"/deals/{deal_id}"))["version"]
    r = seller.browser.patch(
        f"/deals/{deal_id}", json={"expected_version": version, "amount_mnt": 500_000}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_draft"
    # Replaying a funding request with the same key funds once; a second key is refused.
    key = "fund-once-demo"
    first = ok(buyer.browser.act(deal_id, "FUND", key=key))
    replay = ok(buyer.browser.act(deal_id, "FUND", key=key))
    assert replay["replayed"] is True and replay["deal"] == first["deal"]
    assert buyer.browser.act(deal_id, "FUND").status_code == 409
    ok(seller.browser.act(deal_id, "MARK_DELIVERED"))
    ok(buyer.browser.act(deal_id, "CONFIRM_RECEIPT"))
    # Released once: a refund or a second release after completion is refused.
    assert seller.browser.act(deal_id, "REFUND").status_code == 409
    assert buyer.browser.act(deal_id, "CONFIRM_RECEIPT").status_code == 409
    assert (balance(seller), balance(buyer)) == (AMOUNT, 0)
    # The wallet is derived from the immutable ledger, which stays balanced.
    with engine.connect() as conn:
        unbalanced = conn.execute(
            text(
                "SELECT count(*) FROM (SELECT transaction_id FROM ledger_entries GROUP BY "
                "transaction_id HAVING sum(CASE direction WHEN 'DEBIT' THEN amount_mnt ELSE 0 END)"
                " <> sum(CASE direction WHEN 'CREDIT' THEN amount_mnt ELSE 0 END)) t"
            )
        ).scalar_one()
    assert unbalanced == 0
    # There is no endpoint that credits a wallet directly.
    for path in ("/me/wallet", "/me/wallet/deposit", "/me/wallet/topup"):
        assert seller.browser.post(path, json={"amount_mnt": 10**9}).status_code in (404, 405)


def test_demo_mode_keeps_csrf_origin_and_rate_limits(
    seller: Party, buyer: Party, demo: Any
) -> None:
    deal_id = agreed(seller, buyer)
    no_csrf = buyer.browser.post(
        f"/deals/{deal_id}/actions",
        csrf=False,
        json={"action": "FUND"},
        headers={"Idempotency-Key": "k-no-csrf"},
    )
    assert no_csrf.status_code == 403
    foreign = buyer.browser.post(
        f"/deals/{deal_id}/actions",
        json={"action": "FUND"},
        headers={"Origin": "https://evil.example", "Idempotency-Key": "k-evil"},
    )
    assert foreign.status_code == 403
    assert status(seller, deal_id) == "AWAITING_PAYMENT"
    anon = demo()
    assert anon.post("/deals", json=new_deal_body()).status_code in (401, 403)
    codes = [
        anon.post(
            "/auth/register",
            json={"email": f"flood{i}@example.com", "password": PASSWORD, "display_name": "Флүүд"},
        ).status_code
        for i in range(12)
    ]
    assert 429 in codes


# ------------------------------------------------- two keys: API setting + DB policy


def test_database_policy_is_required_too(
    seller: Party, buyer: Party, engine: Engine, demo: Any
) -> None:
    """With the API in demo mode but the owner-set DB policy off, the transition
    function still refuses unverified demo actors, and /ready reports the mismatch."""
    deal_id = agreed(seller, buyer)
    set_policy(engine, False)
    r = buyer.browser.act(deal_id, "FUND")
    assert r.status_code == 403 and r.json()["error"]["code"] == "email_not_verified"
    assert status(seller, deal_id) == "AWAITING_PAYMENT"
    ready = demo().get("/ready")
    assert ready.status_code == 503
    assert ready.json()["checks"]["beta_demo"]["ok"] is False
    set_policy(engine, True)
    assert demo().get("/ready").json()["checks"]["beta_demo"]["ok"] is True
    assert ok(buyer.browser.act(deal_id, "FUND"))["deal"]["status"] == "FUNDED"


def test_runtime_role_cannot_enable_the_policy(app_engine: Engine, engine: Engine) -> None:
    set_policy(engine, False)
    with pytest.raises(DBAPIError, match="permission denied"), app_engine.begin() as conn:
        conn.execute(text("UPDATE platform_policy SET beta_demo_enabled = true WHERE id"))


@pytest.mark.parametrize(("is_demo", "allowed"), [(False, False), (True, True)])
def test_database_exempts_only_demo_accounts(
    engine: Engine, app_engine: Engine, is_demo: bool, allowed: bool
) -> None:
    """Policy on, calling the transition function directly as the runtime role: an
    unverified demo creator may cancel their draft; an unverified non-demo one may not."""
    with Session(engine) as s:
        creator = make_user(s, verified=False)
        creator.is_demo = is_demo
        s.flush()
        deal = Deal(
            reference=f"SP-D{uuid.uuid4().hex[:7].upper()}",
            title="Демо утас",
            amount_mnt=150_000,
            created_by_id=creator.id,
            invite_token_hash=uuid.uuid4().hex * 2,
            is_demo=is_demo,
        )
        s.add(deal)
        s.flush()
        add_participant(s, deal, creator, ParticipantRole.SELLER)
        s.commit()
        deal_id, creator_id = deal.id, creator.id
    call = text("SELECT safepay_transition_deal(:d, 'CANCEL', :u, NULL, NULL, NULL)")
    if allowed:
        with app_engine.begin() as conn:
            conn.execute(call, {"d": deal_id, "u": creator_id})
    else:
        with pytest.raises(DBAPIError, match="not active and verified"), app_engine.begin() as c:
            c.execute(call, {"d": deal_id, "u": creator_id})


def test_unverified_accounts_cannot_claim_email_restricted_invites(
    normal: Any, demo: Any, engine: Engine
) -> None:
    """Demo addresses are unproven: registering someone else's address must not let an
    attacker take an invitation restricted to it, and demo creators cannot restrict."""
    real = normal()
    signup(real, engine, name="Жинхэнэ")
    created = ok(real.post("/deals", json=new_deal_body(counterparty_email="victim@example.com")))
    token = created["invite_url"].rsplit("/", 1)[1]
    squatter = demo()  # demo mode: no verification, so anyone can "own" victim@example.com
    registered = squatter.post(
        "/auth/register",
        json={"email": "victim@example.com", "password": PASSWORD, "display_name": "Халдагч"},
    )
    assert registered.status_code == 202
    ok(squatter.post("/auth/login", json={"email": "victim@example.com", "password": PASSWORD}))
    r = squatter.post(f"/invites/{token}/join")
    assert r.status_code == 403 and r.json()["error"]["code"] == "invite_restricted"

    creator = demo_user(demo, engine, "Демо")
    r = creator.browser.post("/deals", json=new_deal_body(counterparty_email="x@example.com"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "invite_email_unavailable"
    deal_id = ok(creator.browser.post("/deals", json=new_deal_body()))["deal"]["id"]
    r = creator.browser.post(
        f"/deals/{deal_id}/invite", json={"counterparty_email": "x@example.com"}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "invite_email_unavailable"
