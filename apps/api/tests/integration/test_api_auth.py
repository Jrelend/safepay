"""Authentication over real HTTP + PostgreSQL: enumeration, CSRF, sessions,
rate limits, token reuse, cookie flags and suspension."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import URL, Engine, text

from tests.integration.web import (
    ORIGIN,
    PASSWORD,
    Browser,
    admin_login,
    grant_admin,
    latest_link,
    make_settings,
    new_deal_body,
    signup,
    user_id,
)

pytestmark = pytest.mark.usefixtures("fresh_rate_limits")


@pytest.fixture
def browser(app_url: URL) -> Iterator[Browser]:
    yield Browser(make_settings(app_url, "public"))


def test_registration_does_not_reveal_existing_accounts(browser: Browser, engine: Engine) -> None:
    email = signup(browser, engine)
    other = Browser(browser.app.state.settings)
    fresh = f"{uuid.uuid4().hex[:10]}@example.com"
    a = other.post(
        "/auth/register", json={"email": email, "password": PASSWORD, "display_name": "Хэрэглэгч"}
    )
    b = other.post(
        "/auth/register", json={"email": fresh, "password": PASSWORD, "display_name": "Хэрэглэгч"}
    )
    assert (a.status_code, a.json()) == (b.status_code, b.json()) == (202, {"status": "accepted"})
    # The real owner is told by (simulated) email instead.
    with engine.connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM email_outbox "
                    "WHERE to_email = :e AND template = 'account_exists'"
                ),
                {"e": email},
            ).scalar_one()
            == 1
        )


def test_login_failures_are_indistinguishable(browser: Browser, engine: Engine) -> None:
    email = signup(browser, engine)
    other = Browser(browser.app.state.settings)
    wrong = other.post("/auth/login", json={"email": email, "password": "wrong-password-1"})
    unknown = other.post(
        "/auth/login", json={"email": "nobody-here@example.com", "password": "wrong-password-1"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_password_reset_request_does_not_reveal_accounts(browser: Browser, engine: Engine) -> None:
    email = signup(browser, engine)
    known = browser.post("/auth/password-reset/request", json={"email": email})
    unknown = browser.post("/auth/password-reset/request", json={"email": "ghost@example.com"})
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json())


def test_password_hash_never_returned(browser: Browser, engine: Engine) -> None:
    signup(browser, engine)
    me = browser.get("/auth/me").json()
    assert "password" not in str(me).lower()
    assert set(me) == {
        "id",
        "email",
        "display_name",
        "phone_e164",
        "email_verified",
        "is_admin",
        "created_at",
    }


def test_weak_password_rejected(browser: Browser) -> None:
    r = browser.post(
        "/auth/register",
        json={"email": "weak@example.com", "password": "short", "display_name": "Weak"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "weak_password"


def test_unverified_user_cannot_create_deals(browser: Browser, engine: Engine) -> None:
    signup(browser, engine, verify=False)
    r = browser.post("/deals", json=new_deal_body())
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "email_not_verified"


def test_verification_token_is_single_use(browser: Browser, engine: Engine) -> None:
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    browser.post(
        "/auth/register", json={"email": email, "password": PASSWORD, "display_name": "Анар"}
    )
    token = latest_link(engine, email, "verify_email")
    assert browser.post("/auth/verify-email", json={"token": token}).status_code == 200
    again = browser.post("/auth/verify-email", json={"token": token})
    assert again.status_code == 400
    assert browser.post("/auth/verify-email", json={"token": "x" * 43}).status_code == 400


def test_csrf_token_required_for_authenticated_mutations(browser: Browser, engine: Engine) -> None:
    signup(browser, engine)
    missing = browser.post("/deals", json=new_deal_body(), csrf=False)
    forged = browser.post(
        "/deals", json=new_deal_body(), csrf=False, headers={"X-CSRF-Token": "forged"}
    )
    assert missing.status_code == forged.status_code == 403
    assert missing.json()["error"]["code"] == "csrf_failed"
    assert browser.post("/deals", json=new_deal_body()).status_code == 201


@pytest.mark.parametrize("origin", [None, "https://evil.example", "http://web.test.evil.example"])
def test_cross_site_requests_rejected(browser: Browser, engine: Engine, origin: str | None) -> None:
    signup(browser, engine)
    headers = {"X-CSRF-Token": browser.client.cookies.get(browser.csrf_cookie) or ""}
    if origin:
        headers["Origin"] = origin
    r = browser.client.post("/deals", json=new_deal_body(), headers=headers)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "origin_rejected"
    # Login CSRF too (no session yet).
    r = browser.client.post(
        "/auth/login",
        json={"email": "a@example.com", "password": "x" * 12},
        headers={"Origin": origin} if origin else {},
    )
    assert r.status_code == 403


def test_logout_revokes_the_session(browser: Browser, engine: Engine) -> None:
    signup(browser, engine)
    stolen = dict(browser.client.cookies)
    assert browser.post("/auth/logout").status_code == 204
    thief = Browser(browser.app.state.settings)
    thief.client.cookies.update(stolen)
    assert thief.get("/auth/me").status_code == 401


def test_expired_and_idle_sessions_are_rejected(
    browser: Browser, engine: Engine, admin_engine: Engine
) -> None:
    email = signup(browser, engine)
    uid = user_id(engine, email)
    for column, delta in (("last_seen_at", "25 hours"), ("expires_at", "8 days")):
        b = Browser(browser.app.state.settings)
        b.post("/auth/login", json={"email": email, "password": PASSWORD})
        assert b.get("/auth/me").status_code == 200
        with admin_engine.begin() as conn:  # test-only time travel, triggers bypassed
            conn.execute(text("SET LOCAL session_replication_role = replica"))
            conn.execute(
                text(
                    f"UPDATE sessions SET {column} = now() - interval '{delta}', "  # noqa: S608
                    "created_at = now() - interval '9 days' "
                    "WHERE user_id = :u AND revoked_at IS NULL"
                ),
                {"u": uid},
            )
        assert b.get("/auth/me").status_code == 401


def test_login_rate_limited(browser: Browser, engine: Engine) -> None:
    email = signup(browser, engine)
    attacker = Browser(browser.app.state.settings)
    codes = [
        attacker.post(
            "/auth/login", json={"email": email, "password": f"guess-{i}-xxxx"}
        ).status_code
        for i in range(12)
    ]
    assert codes[:9] == [401] * 9
    assert codes[-1] == 429
    # Even the right password is refused while the window is exhausted.
    assert (
        attacker.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 429
    )


def test_password_reset_flow_revokes_sessions(browser: Browser, engine: Engine) -> None:
    email = signup(browser, engine)
    browser.post("/auth/password-reset/request", json={"email": email})
    token = latest_link(engine, email, "password_reset")
    anon = Browser(browser.app.state.settings)
    new = "Another-Strong-Pass-42"
    assert (
        anon.post(
            "/auth/password-reset/confirm", json={"token": token, "new_password": new}
        ).status_code
        == 200
    )
    assert browser.get("/auth/me").status_code == 401  # old session revoked
    assert (
        anon.post(
            "/auth/password-reset/confirm", json={"token": token, "new_password": new}
        ).status_code
        == 400
    )  # single use
    assert anon.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401
    assert anon.post("/auth/login", json={"email": email, "password": new}).status_code == 200


def test_password_change_keeps_current_session_only(browser: Browser, engine: Engine) -> None:
    email = signup(browser, engine)
    second = Browser(browser.app.state.settings)
    second.post("/auth/login", json={"email": email, "password": PASSWORD})
    bad = browser.post(
        "/auth/password/change",
        json={"current_password": "not-it-at-all", "new_password": "Brand-New-Pass-77"},
    )
    assert bad.status_code == 400
    ok = browser.post(
        "/auth/password/change",
        json={"current_password": PASSWORD, "new_password": "Brand-New-Pass-77"},
    )
    assert ok.status_code == 200
    assert browser.get("/auth/me").status_code == 200
    assert second.get("/auth/me").status_code == 401


def test_cannot_revoke_someone_elses_session(browser: Browser, engine: Engine) -> None:
    signup(browser, engine)
    victim = Browser(browser.app.state.settings)
    signup(victim, engine)
    victim_session = victim.get("/auth/sessions").json()[0]["id"]
    assert browser.delete(f"/auth/sessions/{victim_session}").status_code == 404
    assert victim.get("/auth/me").status_code == 200


def test_cookie_flags(app_url: URL, engine: Engine) -> None:
    secure = Browser(make_settings(app_url, "public", cookie_secure=True))
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    secure.post(
        "/auth/register", json={"email": email, "password": PASSWORD, "display_name": "Дулмаа"}
    )
    secure.post("/auth/verify-email", json={"token": latest_link(engine, email, "verify_email")})
    r = secure.post("/auth/login", json={"email": email, "password": PASSWORD})
    cookies = r.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("__Host-safepay_session="))
    csrf = next(c for c in cookies if c.startswith("__Host-safepay_csrf="))
    for c in (session, csrf):
        assert "Secure" in c and "Path=/" in c and "samesite=lax" in c.lower()
        assert "Domain=" not in c
    assert "HttpOnly" in session
    assert "HttpOnly" not in csrf


def test_suspension_revokes_sessions_and_blocks_login(
    app_url: URL, admin_role_url: URL, engine: Engine
) -> None:
    public = Browser(make_settings(app_url, "public"))
    user = Browser(make_settings(app_url, "public"))
    admin_email = signup(public, engine, name="Админ")
    secret = grant_admin(engine, admin_email)
    target = signup(user, engine)
    admin = admin_login(make_settings(admin_role_url, "admin"), engine, admin_email, secret)
    uid = user_id(engine, target)
    no_reason = admin.post(f"/admin/users/{uid}/status", json={"status": "SUSPENDED", "reason": ""})
    assert no_reason.status_code == 422
    r = admin.post(
        f"/admin/users/{uid}/status", json={"status": "SUSPENDED", "reason": "fraud report"}
    )
    assert r.status_code == 204, r.text
    assert user.get("/auth/me").status_code == 401
    again = Browser(make_settings(app_url, "public"))
    r = again.post("/auth/login", json={"email": target, "password": PASSWORD})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "account_suspended"
    assert ORIGIN  # silence unused-import in some linters
