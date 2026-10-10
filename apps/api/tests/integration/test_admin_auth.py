"""Admin authentication is separate from public authentication.

Security-review finding: with the public API's DB credential an attacker could
INSERT a public session (or overwrite a password hash) for an admin and use it on
the admin API. Admin login now needs an admin-only password + TOTP, and admin
sessions live in a table only ``safepay_admin`` can write.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import URL, Engine, text
from sqlalchemy.exc import DBAPIError

from app.core import totp
from app.core.security import hash_password, new_token, sha256_hex
from tests.integration.web import (
    ADMIN_PASSWORD,
    PASSWORD,
    Browser,
    admin_login,
    grant_admin,
    make_settings,
    next_code,
    signup,
    user_id,
)

pytestmark = pytest.mark.usefixtures("fresh_rate_limits")


@pytest.fixture
def admin_setup(app_url: URL, admin_role_url: URL, engine: Engine) -> tuple[str, str, Browser]:
    public = Browser(make_settings(app_url, "public"))
    email = signup(public, engine, name="Админ")
    return email, grant_admin(engine, email), public


def _login(settings: object, email: str, password: str, code: str) -> int:
    b = Browser(settings)  # type: ignore[arg-type]
    return int(
        b.post(
            "/admin/auth/login", json={"email": email, "password": password, "code": code}
        ).status_code
    )


def test_admin_login_requires_admin_password_and_totp(
    admin_role_url: URL, engine: Engine, admin_setup: tuple[str, str, Browser]
) -> None:
    email, secret, _ = admin_setup
    adm = make_settings(admin_role_url, "admin")
    code = next_code(engine, email, secret)
    # The user's ordinary login password is NOT the admin password.
    assert _login(adm, email, PASSWORD, code) == 401
    assert _login(adm, email, ADMIN_PASSWORD, "000000") == 401
    assert _login(adm, email, ADMIN_PASSWORD, code) == 200
    # The same code cannot be replayed.
    assert _login(adm, email, ADMIN_PASSWORD, code) == 401


def test_failures_are_indistinguishable(
    admin_role_url: URL, engine: Engine, admin_setup: tuple[str, str, Browser]
) -> None:
    email, _secret, _ = admin_setup
    b = Browser(make_settings(admin_role_url, "admin"))
    bodies = [
        b.post("/admin/auth/login", json={"email": e, "password": p, "code": "123456"}).json()
        for e, p in ((email, "wrong-password-1"), ("ghost@example.com", ADMIN_PASSWORD))
    ]
    assert bodies[0] == bodies[1]


def test_admin_cookies_are_strict_and_session_logs_out(
    admin_role_url: URL, engine: Engine, admin_setup: tuple[str, str, Browser]
) -> None:
    email, secret, _ = admin_setup
    adm = make_settings(admin_role_url, "admin", cookie_secure=True)
    b = Browser(adm)
    r = b.post(
        "/admin/auth/login",
        json={"email": email, "password": ADMIN_PASSWORD, "code": next_code(engine, email, secret)},
    )
    cookies = r.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("__Host-safepay_admin="))
    assert "HttpOnly" in session and "Secure" in session and "samesite=strict" in session.lower()
    assert b.get("/admin/overview").status_code == 200
    # CSRF token is required on unsafe admin requests.
    assert b.post("/admin/auth/logout", csrf=False).status_code == 403
    assert b.post("/admin/auth/logout").status_code == 204
    assert b.get("/admin/overview").status_code == 401


def test_admin_session_idle_timeout(
    admin_role_url: URL, engine: Engine, admin_setup: tuple[str, str, Browser]
) -> None:
    email, secret, _ = admin_setup
    b = admin_login(make_settings(admin_role_url, "admin"), engine, email, secret)
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE admin_sessions SET last_seen_at = now() - interval '31 minutes' "
                "WHERE admin_user_id = :u"
            ),
            {"u": user_id(engine, email)},
        )
    assert b.get("/admin/overview").status_code == 401


def test_suspended_admin_loses_admin_session(
    admin_role_url: URL, engine: Engine, admin_setup: tuple[str, str, Browser]
) -> None:
    email, secret, _ = admin_setup
    b = admin_login(make_settings(admin_role_url, "admin"), engine, email, secret)
    with engine.begin() as conn:
        conn.execute(text("UPDATE users SET status = 'SUSPENDED' WHERE email = :e"), {"e": email})
    try:
        assert b.get("/admin/overview").status_code == 401
    finally:
        with engine.begin() as conn:
            conn.execute(text("UPDATE users SET status = 'ACTIVE' WHERE email = :e"), {"e": email})


def test_leaked_public_credential_cannot_become_admin(
    admin_role_url: URL,
    engine: Engine,
    app_engine: Engine,
    admin_setup: tuple[str, str, Browser],
) -> None:
    """The exact escalation from the review, attempted with the safepay_app role."""
    email, _secret, _ = admin_setup
    admin_id = user_id(engine, email)
    token, csrf = new_token(), new_token()
    # 1. Forge a PUBLIC session for the admin (the app role may insert sessions).
    with app_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sessions (token_hash, csrf_hash, user_id, expires_at) "
                "VALUES (:t, :c, :u, :x)"
            ),
            {
                "t": sha256_hex(token),
                "c": sha256_hex(csrf),
                "u": admin_id,
                "x": datetime.now(UTC) + timedelta(days=1),
            },
        )
    b = Browser(make_settings(admin_role_url, "admin"))
    for name in ("safepay_session", "safepay_admin"):
        b.client.cookies.set(name, token)
    assert b.get("/admin/overview").status_code == 401
    # 2. Neither read nor write the admin credentials or sessions.
    for sql, params in (
        ("SELECT password_hash FROM admins", {}),
        ("SELECT totp_secret FROM admins", {}),
        ("SELECT * FROM admin_sessions", {}),
        ("UPDATE admins SET password_hash = :h", {"h": hash_password("x" * 12)}),
        ("UPDATE admins SET totp_last_step = 0", {}),
        (
            "INSERT INTO admin_sessions (token_hash, csrf_hash, admin_user_id, expires_at) "
            "VALUES (:t, :t, :u, now() + interval '1 hour')",
            {"t": sha256_hex(token), "u": admin_id},
        ),
    ):
        with app_engine.connect() as conn, pytest.raises(DBAPIError, match="permission denied"):
            conn.execute(text(sql), params)
    # The app role can still tell whether someone is an admin (badge only).
    with app_engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT user_id FROM admins WHERE user_id = :u"), {"u": admin_id}
            ).scalar_one()
            == admin_id
        )


def test_admin_role_no_longer_reads_public_sessions(admin_api_engine: Engine) -> None:
    with admin_api_engine.connect() as conn, pytest.raises(DBAPIError, match="permission denied"):
        conn.execute(text("SELECT * FROM sessions"))


def test_admin_sessions_are_tamper_proof_for_the_admin_role(
    admin_role_url: URL,
    engine: Engine,
    admin_api_engine: Engine,
    admin_setup: tuple[str, str, Browser],
) -> None:
    email, secret, _ = admin_setup
    admin_login(make_settings(admin_role_url, "admin"), engine, email, secret)
    with admin_api_engine.begin() as conn:
        conn.execute(text("UPDATE admin_sessions SET revoked_at = now() WHERE revoked_at IS NULL"))
    for sql in (
        "UPDATE admin_sessions SET revoked_at = NULL",
        "UPDATE admin_sessions SET expires_at = now() + interval '30 days'",
        "UPDATE admins SET totp_last_step = 0",
        "DELETE FROM admin_sessions",
    ):
        with admin_api_engine.connect() as conn, pytest.raises(DBAPIError):
            conn.execute(text(sql))


def test_totp_code_cannot_be_replayed_concurrently_or_rewound(
    engine: Engine, admin_setup: tuple[str, str, Browser]
) -> None:
    email, _secret, _ = admin_setup
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE admins SET totp_last_step = :s WHERE user_id = :u"),
            {"s": totp.current_step(), "u": user_id(engine, email)},
        )
    with engine.connect() as conn, pytest.raises(DBAPIError, match="cannot move backwards"):
        conn.execute(
            text("UPDATE admins SET totp_last_step = 1 WHERE user_id = :u"),
            {"u": user_id(engine, email)},
        )
    assert uuid.UUID(str(user_id(engine, email)))
