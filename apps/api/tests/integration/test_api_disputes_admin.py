"""Disputes, evidence and the separate admin API over real HTTP + PostgreSQL roles."""

import io
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import URL, Engine, text
from sqlalchemy.exc import DBAPIError

from tests.integration.web import (
    Browser,
    admin_login,
    grant_admin,
    make_settings,
    new_deal_body,
    signup,
)

pytestmark = pytest.mark.usefixtures("fresh_rate_limits")
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.7\n" + b"0" * 64


@dataclass
class World:
    seller: Browser
    buyer: Browser
    stranger: Browser
    admin_public: Browser  # the admin's session on the public API
    admin: Browser  # the same session on the admin API
    deal_id: str
    dispute_id: str
    public_settings: Any
    admin_settings: Any


def ok(r: Any) -> Any:
    assert r.status_code in (200, 201), r.text
    return r.json()


def agreed_and_funded(seller: Browser, buyer: Browser) -> str:
    r = ok(seller.post("/deals", json=new_deal_body()))
    deal_id, token = r["deal"]["id"], r["invite_url"].rsplit("/", 1)[1]
    ok(buyer.post(f"/invites/{token}/join"))
    ok(seller.act(deal_id, "SUBMIT"))
    ok(buyer.act(deal_id, "ACCEPT"))
    ok(buyer.act(deal_id, "FUND"))
    ok(seller.act(deal_id, "MARK_DELIVERED"))
    return str(deal_id)


@pytest.fixture
def world(app_url: URL, admin_role_url: URL, engine: Engine) -> World:
    pub = make_settings(app_url, "public")
    adm = make_settings(admin_role_url, "admin")
    seller, buyer, stranger, admin_public = (Browser(pub) for _ in range(4))
    signup(seller, engine, name="Худалдагч")
    signup(buyer, engine, name="Худалдан авагч")
    signup(stranger, engine, name="Гадны хүн")
    admin_email = signup(admin_public, engine, name="Админ")
    secret = grant_admin(engine, admin_email)
    admin = admin_login(adm, engine, admin_email, secret)
    deal_id = agreed_and_funded(seller, buyer)
    deal = ok(buyer.act(deal_id, "OPEN_DISPUTE", note="Бараа эвдэрсэн ирсэн"))["deal"]
    assert deal["status"] == "DISPUTED" and deal["dispute_id"]
    return World(
        seller, buyer, stranger, admin_public, admin, deal_id, deal["dispute_id"], pub, adm
    )


def upload(b: Browser, dispute_id: str, name: str, data: bytes, ctype: str = "image/png") -> Any:
    return b.post(
        f"/disputes/{dispute_id}/files",
        files={"file": (name, io.BytesIO(data), ctype)},
        data={"caption": "зураг"},
    )


def test_open_dispute_requires_reason(app_url: URL, engine: Engine) -> None:
    pub = make_settings(app_url, "public")
    seller, buyer = Browser(pub), Browser(pub)
    signup(seller, engine)
    signup(buyer, engine)
    deal_id = agreed_and_funded(seller, buyer)
    r = buyer.act(deal_id, "OPEN_DISPUTE")
    assert r.status_code == 422 and r.json()["error"]["code"] == "reason_required"


def test_participants_add_evidence_and_strangers_see_nothing(world: World) -> None:
    d = world.dispute_id
    ok(world.seller.post(f"/disputes/{d}/statements", json={"body": "Сайн байдалтай илгээсэн"}))
    view = ok(upload(world.buyer, d, "photo.png", PNG))
    item = next(e for e in view["evidence"] if e["kind"] == "FILE")
    assert item["mine"] is True and item["content_type"] == "image/png"
    for b in (world.stranger, world.admin_public):  # admin's *public* session is just a user
        assert b.get(f"/disputes/{d}").status_code == 404
        assert b.get(f"/disputes/{d}/evidence/{item['id']}/file").status_code == 404
        assert b.post(f"/disputes/{d}/statements", json={"body": "x"}).status_code == 404
        assert upload(b, d, "p.png", PNG).status_code == 404
    f = world.seller.get(f"/disputes/{d}/evidence/{item['id']}/file")
    assert f.status_code == 200 and f.content == PNG
    assert f.headers["content-disposition"].startswith("attachment")
    assert f.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in f.headers["content-security-policy"]
    assert "no-store" in f.headers["cache-control"]


@pytest.mark.parametrize(
    ("name", "data", "ctype", "code"),
    [
        ("evil.png", b"<html><script>alert(1)</script>", "image/png", "unsupported_file_type"),
        (
            "x.svg",
            b"<svg xmlns='http://www.w3.org/2000/svg'/>",
            "image/svg+xml",
            "unsupported_file_type",
        ),
        ("big.pdf", b"%PDF-" + b"0" * (2 * 1024 * 1024), "application/pdf", "file_too_large"),
        ("empty.png", b"", "image/png", "empty_file"),
    ],
)
def test_file_sniffing_and_limits(
    world: World, name: str, data: bytes, ctype: str, code: str
) -> None:
    r = upload(world.buyer, world.dispute_id, name, data, ctype)
    assert r.status_code in (413, 422), r.text
    assert r.json()["error"]["code"] == code


def test_file_names_are_sanitized(world: World) -> None:
    view = ok(upload(world.buyer, world.dispute_id, "../../etc/passwd\r\n.pdf", PDF, "text/html"))
    item = next(e for e in view["evidence"] if e["kind"] == "FILE")
    assert "/" not in item["file_name"] and "\n" not in item["file_name"]
    assert item["content_type"] == "application/pdf"  # sniffed, not the client's claim


def test_evidence_is_immutable_for_every_role(
    world: World, app_engine: Engine, admin_api_engine: Engine, engine: Engine
) -> None:
    ok(
        world.buyer.post(
            f"/disputes/{world.dispute_id}/statements", json={"body": "Анхны мэдүүлэг"}
        )
    )
    for eng, expected in (
        (app_engine, "permission denied"),
        (admin_api_engine, "permission denied"),
        (engine, "append-only"),
    ):
        for sql in ("UPDATE dispute_evidence SET body = 'edited'", "DELETE FROM dispute_evidence"):
            with eng.connect() as conn, pytest.raises(DBAPIError, match=expected):
                conn.execute(text(sql))


def test_public_api_has_no_admin_routes(world: World) -> None:
    for path in ("/admin/overview", "/admin/disputes", "/admin/users"):
        assert world.admin_public.get(path).status_code == 404


def test_public_sessions_are_not_accepted_by_admin_api(world: World) -> None:
    """Neither a buyer's nor even an admin's PUBLIC session works on the admin API."""
    for public in (world.buyer, world.admin_public):
        b = Browser(world.admin_settings)
        b.client.cookies.update(dict(public.client.cookies))
        assert b.get("/admin/overview").status_code == 401
        assert b.get("/admin/auth/me").status_code == 401


def test_non_admin_is_refused_by_admin_api(world: World, engine: Engine) -> None:
    b = Browser(world.admin_settings)
    # A normal user cannot log in to the admin API at all (no admin credentials).
    login = b.post(
        "/admin/auth/login",
        json={"email": "nobody@example.com", "password": "x" * 12, "code": "123456"},
    )
    assert login.status_code == 401
    for path in (
        "/admin/overview",
        "/admin/disputes",
        f"/admin/disputes/{world.dispute_id}",
        "/admin/users",
        "/admin/audit",
    ):
        assert b.get(path).status_code == 401
    r = b.post(
        f"/admin/disputes/{world.dispute_id}/decision",
        json={"outcome": "REFUND_TO_BUYER", "reason": "өөртөө буцаалт"},
    )
    assert r.status_code in (401, 403)
    anon = Browser(world.admin_settings)
    assert anon.get("/admin/overview").status_code == 401


def test_admin_decision_refunds_and_is_audited(world: World, engine: Engine) -> None:
    a, d = world.admin, world.dispute_id
    assert d in {x["id"] for x in ok(a.get("/admin/disputes"))}
    ok(a.post(f"/admin/disputes/{d}/notes", json={"body": "Хоёр талын нотлох баримтыг шалгав"}))
    short = a.post(
        f"/admin/disputes/{d}/decision", json={"outcome": "REFUND_TO_BUYER", "reason": "short"}
    )
    assert short.status_code == 422
    missing_csrf = a.post(
        f"/admin/disputes/{d}/decision",
        csrf=False,
        json={"outcome": "REFUND_TO_BUYER", "reason": "Бараа эвдэрсэн нь нотлогдсон"},
    )
    assert missing_csrf.status_code == 403
    out = ok(
        a.post(
            f"/admin/disputes/{d}/decision",
            json={"outcome": "REFUND_TO_BUYER", "reason": "Бараа эвдэрсэн нь нотлогдсон"},
        )
    )
    assert out["status"] == "RESOLVED" and out["deal_status"] == "REFUNDED"
    again = a.post(
        f"/admin/disputes/{d}/decision",
        json={"outcome": "RELEASE_TO_SELLER", "reason": "Дахин шийдвэрлэх оролдлого"},
    )
    assert again.status_code == 409
    assert ok(world.buyer.get("/me/wallet"))["balance_mnt"] == "1250000"
    assert ok(world.seller.get("/me/wallet"))["balance_mnt"] == "0"
    view = ok(world.buyer.get(f"/disputes/{d}"))
    assert view["outcome"] == "REFUND_TO_BUYER" and view["decision_reason"]
    # Internal admin notes never reach participants.
    assert all(e["kind"] != "ADMIN_NOTE" for e in view["evidence"])
    assert world.buyer.post(f"/disputes/{d}/statements", json={"body": "хожуу"}).status_code == 409
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT actor_type, actor_user_id FROM audit_events "
                "WHERE deal_id = :d AND data->>'action' = 'RESOLVE_REFUND'"
            ),
            {"d": world.deal_id},
        ).one()
    assert row.actor_type == "ADMIN" and row.actor_user_id is not None
    audit = ok(a.get("/admin/audit"))
    assert any(e["deal_id"] == world.deal_id and e["actor_type"] == "ADMIN" for e in audit)


def test_admin_cannot_decide_own_deal(world: World, engine: Engine) -> None:
    # The admin is the seller in a new disputed deal.
    deal_id = agreed_and_funded(world.admin_public, world.buyer)
    dispute_id = ok(world.buyer.act(deal_id, "OPEN_DISPUTE", note="Хүргэгдээгүй"))["deal"][
        "dispute_id"
    ]
    r = world.admin.post(
        f"/admin/disputes/{dispute_id}/decision",
        json={"outcome": "RELEASE_TO_SELLER", "reason": "Өөрийн гүйлгээг шийдэх оролдлого"},
    )
    assert r.status_code == 403, r.text
    assert ok(world.buyer.get(f"/deals/{deal_id}"))["status"] == "DISPUTED"


def test_admin_cannot_suspend_self_or_unknown_user(world: World, engine: Engine) -> None:
    me = ok(world.admin_public.get("/auth/me"))["id"]
    r = world.admin.post(
        f"/admin/users/{me}/status", json={"status": "SUSPENDED", "reason": "өөрийгөө"}
    )
    assert r.status_code in (403, 409, 422), r.text
    r = world.admin.post(
        f"/admin/users/{uuid.uuid4()}/status",
        json={"status": "SUSPENDED", "reason": "байхгүй хэрэглэгч"},
    )
    assert r.status_code == 404
