"""Deals over real HTTP + PostgreSQL: lifecycle, IDOR, invitations, idempotency, races."""

import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import URL, Engine, text

from tests.integration.web import Browser, make_settings, new_deal_body, signup, user_id

pytestmark = pytest.mark.usefixtures("fresh_rate_limits")
BANNER_FREE_STATUSES = {"DRAFT", "PENDING_ACCEPTANCE"}


@dataclass
class Party:
    browser: Browser
    email: str


@pytest.fixture
def new_browser(app_url: URL) -> Iterator[Any]:
    settings = make_settings(app_url, "public")
    yield lambda: Browser(settings)


@pytest.fixture
def seller(new_browser: Any, engine: Engine) -> Party:
    b = new_browser()
    return Party(b, signup(b, engine, name="Худалдагч"))


@pytest.fixture
def buyer(new_browser: Any, engine: Engine) -> Party:
    b = new_browser()
    return Party(b, signup(b, engine, name="Худалдан авагч"))


@pytest.fixture
def stranger(new_browser: Any, engine: Engine) -> Party:
    b = new_browser()
    return Party(b, signup(b, engine, name="Гадны хүн"))


def invite_token(url: str) -> str:
    return url.rsplit("/", 1)[1]


def create(seller: Party, **kw: Any) -> tuple[str, str]:
    r = seller.browser.post("/deals", json=new_deal_body(**kw))
    assert r.status_code == 201, r.text
    return r.json()["deal"]["id"], invite_token(r.json()["invite_url"])


def ok(r: Any) -> Any:
    assert r.status_code == 200, r.text
    return r.json()


def agreed_deal(seller: Party, buyer: Party, **kw: Any) -> str:
    deal_id, token = create(seller, **kw)
    ok(buyer.browser.post(f"/invites/{token}/join"))
    ok(seller.browser.act(deal_id, "SUBMIT"))
    deal = ok(buyer.browser.act(deal_id, "ACCEPT"))["deal"]
    assert deal["status"] == "AWAITING_PAYMENT"
    return deal_id


def test_full_lifecycle_moves_simulated_money(seller: Party, buyer: Party) -> None:
    deal_id = agreed_deal(seller, buyer)
    funded = ok(buyer.browser.act(deal_id, "FUND"))
    assert funded["deal"]["status"] == "FUNDED" and funded["ledger_transaction_id"]
    assert "MARK_DELIVERED" in ok(seller.browser.get(f"/deals/{deal_id}"))["actions"]
    ok(seller.browser.act(deal_id, "MARK_DELIVERED"))
    done = ok(buyer.browser.act(deal_id, "CONFIRM_RECEIPT"))["deal"]
    assert done["status"] == "COMPLETED"
    wallet = ok(seller.browser.get("/me/wallet"))
    assert wallet["simulated"] is True
    assert wallet["balance_mnt"] == "1250000"
    postings = ok(buyer.browser.get(f"/deals/{deal_id}/escrow"))
    assert [p["kind"] for p in postings] == ["ESCROW_HOLD", "ESCROW_RELEASE"]
    actions = [e["data"].get("action") for e in ok(buyer.browser.get(f"/deals/{deal_id}/timeline"))]
    for a in ("SUBMIT", "ACCEPT", "FUND", "MARK_DELIVERED", "CONFIRM_RECEIPT"):
        assert a in actions
    unread = ok(seller.browser.get("/me/notifications"))["unread"]
    assert unread >= 1


def test_amounts_are_serialized_as_strings(seller: Party) -> None:
    r = seller.browser.post("/deals", json=new_deal_body(amount_mnt=100_000_000_000))
    assert r.status_code == 201
    assert r.json()["deal"]["amount_mnt"] == "100000000000"
    for bad in (99, 100_000_000_001, -5, 1.5, "1e3"):
        assert seller.browser.post("/deals", json=new_deal_body(amount_mnt=bad)).status_code == 422


def test_incompatible_terms_rejected(seller: Party) -> None:
    r = seller.browser.post(
        "/deals", json=new_deal_body(item_type="DIGITAL_GOODS", delivery_method="COURIER")
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "incompatible_terms"


def test_supplied_actor_and_user_fields_are_ignored(seller: Party, buyer: Party) -> None:
    """A buyer cannot claim to be the seller, SYSTEM or ADMIN, or name another user."""
    deal_id = agreed_deal(seller, buyer)
    ok(buyer.browser.act(deal_id, "FUND"))
    seller_id = str(user_id_of(seller))
    for extra in (
        {"actor": "SELLER"},
        {"actor": "SYSTEM"},
        {"actor_user_id": seller_id},
        {"acting_user_id": seller_id},
    ):
        r = buyer.browser.act(deal_id, "MARK_DELIVERED", **extra)
        assert r.status_code in (409, 422), (extra, r.text)
    for action in ("AUTO_RELEASE", "EXPIRE", "REFUND", "RESOLVE_RELEASE", "RESOLVE_REFUND"):
        r = buyer.browser.act(deal_id, action)
        assert r.status_code in (409, 422), (action, r.text)
    assert ok(buyer.browser.get(f"/deals/{deal_id}"))["status"] == "FUNDED"


_ENGINE: dict[str, Engine] = {}


@pytest.fixture(autouse=True)
def _remember_engine(engine: Engine) -> None:
    _ENGINE["owner"] = engine


def user_id_of(p: Party) -> uuid.UUID:
    return user_id(_ENGINE["owner"], p.email)


def test_non_participants_cannot_see_or_touch_a_deal(
    seller: Party, buyer: Party, stranger: Party
) -> None:
    deal_id = agreed_deal(seller, buyer)
    s = stranger.browser
    for path in ("", "/timeline", "/escrow"):
        assert s.get(f"/deals/{deal_id}{path}").status_code == 404
    assert s.act(deal_id, "FUND").status_code == 404
    assert (
        s.patch(f"/deals/{deal_id}", json={"expected_version": 1, "title": "Hijack"}).status_code
        == 404
    )
    assert s.post(f"/deals/{deal_id}/invite", json={}).status_code == 404
    # An unknown id looks exactly the same (no existence oracle).
    missing = s.get(f"/deals/{uuid.uuid4()}")
    assert missing.status_code == 404 and missing.json() == s.get(f"/deals/{deal_id}").json()
    assert deal_id not in {d["id"] for d in ok(s.get("/deals"))}
    assert ok(buyer.browser.get(f"/deals/{deal_id}"))["status"] == "AWAITING_PAYMENT"


def test_anonymous_requests_rejected(new_browser: Any, seller: Party) -> None:
    deal_id, _ = create(seller)
    anon = new_browser()
    for path in (f"/deals/{deal_id}", "/deals", "/me/wallet", "/me/notifications"):
        assert anon.get(path).status_code == 401
    assert anon.post("/deals", json=new_deal_body()).status_code in (401, 403)


def test_cannot_deal_with_yourself(seller: Party) -> None:
    r = seller.browser.post("/deals", json=new_deal_body(counterparty_email=seller.email))
    assert r.status_code == 422 and r.json()["error"]["code"] == "self_deal"
    _, token = create(seller)
    r = seller.browser.post(f"/invites/{token}/join")
    assert r.status_code == 422 and r.json()["error"]["code"] == "self_deal"


def test_invite_restricted_to_named_email(seller: Party, buyer: Party, stranger: Party) -> None:
    _, token = create(seller, counterparty_email=buyer.email)
    r = stranger.browser.get(f"/invites/{token}")
    assert r.status_code == 403 and r.json()["error"]["code"] == "invite_restricted"
    assert stranger.browser.post(f"/invites/{token}/join").status_code == 403
    assert ok(buyer.browser.get(f"/invites/{token}"))["offered_role"] == "BUYER"
    ok(buyer.browser.post(f"/invites/{token}/join"))
    # The link is single use.
    assert stranger.browser.post(f"/invites/{token}/join").status_code in (403, 404, 409)


def test_invite_tokens_are_not_guessable_or_reusable_after_rotation(
    seller: Party, buyer: Party
) -> None:
    deal_id, old = create(seller)
    assert buyer.browser.get(f"/invites/{'A' * 43}").status_code == 404
    new = invite_token(ok(seller.browser.post(f"/deals/{deal_id}/invite", json={}))["invite_url"])
    assert new != old
    assert buyer.browser.post(f"/invites/{old}/join").status_code == 404
    ok(buyer.browser.post(f"/invites/{new}/join"))


def test_counterparty_cannot_edit_draft_and_terms_freeze(seller: Party, buyer: Party) -> None:
    deal_id, token = create(seller)
    ok(buyer.browser.post(f"/invites/{token}/join"))
    r = buyer.browser.patch(f"/deals/{deal_id}", json={"expected_version": 1, "amount_mnt": 100})
    assert r.status_code == 403
    v = ok(seller.browser.get(f"/deals/{deal_id}"))["version"]
    edited = ok(
        seller.browser.patch(
            f"/deals/{deal_id}", json={"expected_version": v, "amount_mnt": 900_000}
        )
    )
    assert edited["amount_mnt"] == "900000"
    stale = seller.browser.patch(
        f"/deals/{deal_id}", json={"expected_version": v, "title": "Old version"}
    )
    assert stale.status_code == 409
    ok(seller.browser.act(deal_id, "SUBMIT"))
    ok(buyer.browser.act(deal_id, "ACCEPT"))
    v = ok(seller.browser.get(f"/deals/{deal_id}"))["version"]
    frozen = seller.browser.patch(
        f"/deals/{deal_id}", json={"expected_version": v, "amount_mnt": 100}
    )
    assert frozen.status_code == 409 and frozen.json()["error"]["code"] == "not_draft"


def test_decline_and_cancel(seller: Party, buyer: Party) -> None:
    deal_id, token = create(seller)
    ok(buyer.browser.post(f"/invites/{token}/join"))
    ok(seller.browser.act(deal_id, "SUBMIT"))
    assert (
        ok(buyer.browser.act(deal_id, "DECLINE", note="Үнэ өндөр"))["deal"]["status"] == "CANCELLED"
    )
    other, _ = create(seller)
    assert ok(seller.browser.act(other, "CANCEL"))["deal"]["status"] == "CANCELLED"


def test_idempotency_key_required_and_replayed(seller: Party, buyer: Party, engine: Engine) -> None:
    deal_id = agreed_deal(seller, buyer)
    r = buyer.browser.post(f"/deals/{deal_id}/actions", json={"action": "FUND"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "idempotency_key_required"
    first = ok(buyer.browser.act(deal_id, "FUND", key="fund-1"))
    again = ok(buyer.browser.act(deal_id, "FUND", key="fund-1"))
    assert again["replayed"] is True
    assert again["ledger_transaction_id"] == first["ledger_transaction_id"]
    reused = buyer.browser.act(deal_id, "CANCEL", key="fund-1")
    assert reused.status_code == 409 and reused.json()["error"]["code"] == "idempotency_key_reused"
    # A fresh key cannot fund twice.
    assert buyer.browser.act(deal_id, "FUND").status_code == 409
    # Another user may use the same key string without colliding.
    assert seller.browser.act(deal_id, "MARK_DELIVERED", key="fund-1").status_code == 200
    with engine.connect() as conn:
        n = conn.execute(
            text(
                "SELECT count(*) FROM ledger_transactions "
                "WHERE deal_id = :d AND kind = 'ESCROW_HOLD'"
            ),
            {"d": deal_id},
        ).scalar_one()
    assert n == 1


def test_concurrent_funding_with_distinct_keys_funds_once(
    seller: Party, buyer: Party, new_browser: Any, engine: Engine
) -> None:
    deal_id = agreed_deal(seller, buyer)
    tabs = []
    for _ in range(6):  # six "tabs" sharing the buyer's session
        tab = new_browser()
        tab.client.cookies.update(dict(buyer.browser.client.cookies))
        tabs.append(tab)
    barrier = threading.Barrier(len(tabs))
    codes: list[int] = []

    def go(tab: Browser) -> None:
        barrier.wait()
        codes.append(tab.act(deal_id, "FUND").status_code)

    threads = [threading.Thread(target=go, args=(t,)) for t in tabs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(codes) == [200] + [409] * 5, codes
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM ledger_transactions WHERE deal_id = :d"), {"d": deal_id}
            ).scalar_one()
            == 1
        )


def test_release_vs_dispute_race_settles_once(
    seller: Party, buyer: Party, new_browser: Any, engine: Engine
) -> None:
    deal_id = agreed_deal(seller, buyer)
    ok(buyer.browser.act(deal_id, "FUND"))
    ok(seller.browser.act(deal_id, "MARK_DELIVERED"))
    tab = new_browser()
    tab.client.cookies.update(dict(buyer.browser.client.cookies))
    barrier = threading.Barrier(2)
    out: dict[str, int] = {}

    def run(name: str, b: Browser, action: str, **kw: Any) -> None:
        barrier.wait()
        out[name] = b.act(deal_id, action, **kw).status_code

    a = threading.Thread(target=run, args=("confirm", buyer.browser, "CONFIRM_RECEIPT"))
    d = threading.Thread(
        target=run, args=("dispute", tab, "OPEN_DISPUTE"), kwargs={"note": "Эвдэрсэн ирсэн"}
    )
    for t in (a, d):
        t.start()
    for t in (a, d):
        t.join(30)
    assert sorted(out.values()) == [200, 409], out
    with engine.connect() as conn:
        settled = conn.execute(
            text(
                "SELECT count(*) FROM ledger_transactions "
                "WHERE deal_id = :d AND kind IN ('ESCROW_RELEASE', 'ESCROW_REFUND')"
            ),
            {"d": deal_id},
        ).scalar_one()
    assert settled == (1 if out["confirm"] == 200 else 0)


def test_unverified_user_cannot_join_or_act(
    seller: Party, new_browser: Any, engine: Engine
) -> None:
    _, token = create(seller)
    b = new_browser()
    signup(b, engine, verify=False)
    assert b.post(f"/invites/{token}/join").status_code == 403
    assert b.get(f"/invites/{token}").status_code == 403


def test_list_scopes(seller: Party, buyer: Party) -> None:
    active = agreed_deal(seller, buyer)
    closed, _ = create(seller)
    ok(seller.browser.act(closed, "CANCEL"))

    def ids(scope: str) -> set[str]:
        return {d["id"] for d in ok(seller.browser.get(f"/deals?scope={scope}"))}

    assert active in ids("active") and closed not in ids("active")
    assert closed in ids("closed") and active not in ids("closed")
