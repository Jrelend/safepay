"""Browser-like HTTP clients for the public and admin APIs (real PostgreSQL roles)."""

import re
import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import URL, Engine, text

from app.core import totp
from app.core.config import Settings
from app.core.security import hash_password
from app.main import create_app

ORIGIN = "http://web.test"
PASSWORD = "Correct-Horse-Battery-9"


def make_settings(url: URL, mode: str, **extra: Any) -> Settings:
    return Settings(
        app_env="test",
        api_mode=mode,  # type: ignore[arg-type]
        database_url=url.render_as_string(hide_password=False),  # type: ignore[arg-type]
        cors_allowed_origins=[ORIGIN],
        public_web_url=ORIGIN,
        dev_mailbox_enabled=True,
        db_pool_size=1,  # many short-lived test apps share each role's connection limit
        **extra,
    )


_OPEN: list["Browser"] = []


def close_all() -> None:
    """Dispose every test app's engine (role connection limits are small)."""
    while _OPEN:
        _OPEN.pop().app.state.engine.dispose()


class Browser:
    """Keeps cookies, sends Origin, echoes the CSRF cookie on unsafe requests."""

    def __init__(self, settings: Settings) -> None:
        self.app = create_app(settings)
        _OPEN.append(self)
        scheme = "https" if settings.secure_cookies else "http"  # Secure cookies need https
        self.client = TestClient(self.app, base_url=f"{scheme}://api.test")
        prefix = "__Host-" if settings.secure_cookies else ""
        name = "safepay_admin_csrf" if settings.api_mode == "admin" else "safepay_csrf"
        self.csrf_cookie = prefix + name

    def request(self, method: str, path: str, *, csrf: bool = True, **kw: Any) -> Any:
        headers = {"Origin": ORIGIN, **kw.pop("headers", {})}
        token = self.client.cookies.get(self.csrf_cookie)
        if csrf and token and method in ("POST", "PUT", "PATCH", "DELETE"):
            headers.setdefault("X-CSRF-Token", token)
        return self.client.request(method, path, headers=headers, **kw)

    def get(self, path: str, **kw: Any) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> Any:
        return self.request("POST", path, **kw)

    def patch(self, path: str, **kw: Any) -> Any:
        return self.request("PATCH", path, **kw)

    def delete(self, path: str, **kw: Any) -> Any:
        return self.request("DELETE", path, **kw)

    def act(self, deal_id: str, action: str, *, key: str | None = None, **body: Any) -> Any:
        return self.post(
            f"/deals/{deal_id}/actions",
            json={"action": action, **body},
            headers={"Idempotency-Key": key or f"k-{uuid.uuid4()}"},
        )


def latest_link(owner: Engine, email: str, template: str) -> str:
    """Read the newest simulated email's one-time link token."""
    with owner.connect() as conn:
        link = conn.execute(
            text(
                "SELECT data->>'link' FROM email_outbox WHERE to_email = :e AND template = :t "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"e": email, "t": template},
        ).scalar_one()
    match = re.search(r"token=([A-Za-z0-9_\-]+)", link)
    assert match, link
    return match.group(1)


def signup(browser: Browser, owner: Engine, *, name: str = "Бат", verify: bool = True) -> str:
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    r = browser.post(
        "/auth/register", json={"email": email, "password": PASSWORD, "display_name": name}
    )
    assert r.status_code == 202, r.text
    if verify:
        token = latest_link(owner, email, "verify_email")
        assert browser.post("/auth/verify-email", json={"token": token}).status_code == 200
    r = browser.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return email


def user_id(owner: Engine, email: str) -> uuid.UUID:
    with owner.connect() as conn:
        uid: uuid.UUID = conn.execute(
            text("SELECT id FROM users WHERE email = :e"), {"e": email}
        ).scalar_one()
    return uid


ADMIN_PASSWORD = "Separate-Admin-Secret-77"


def grant_admin(owner: Engine, email: str) -> str:
    """Grant admin with a separate admin password + TOTP secret (as the owner CLI does).
    Returns the TOTP secret."""
    secret = totp.new_secret()
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO admins (user_id, note, password_hash, totp_secret) "
                "SELECT id, 'test', :h, :s FROM users WHERE email = :e"
            ),
            {"e": email, "h": hash_password(ADMIN_PASSWORD), "s": secret},
        )
    return secret


def next_code(owner: Engine, email: str, secret: str) -> str:
    """A TOTP code the server will still accept (codes are single-use per step)."""
    with owner.connect() as conn:
        last = conn.execute(
            text(
                "SELECT a.totp_last_step FROM admins a JOIN users u ON u.id = a.user_id "
                "WHERE u.email = :e"
            ),
            {"e": email},
        ).scalar_one()
    step = max(totp.current_step(), last + 1)
    return totp.code_at(secret, step)


def admin_login(admin_settings: Settings, owner: Engine, email: str, secret: str) -> "Browser":
    """A browser signed in to the ADMIN API with its own admin session."""
    b = Browser(admin_settings)
    r = b.post(
        "/admin/auth/login",
        json={"email": email, "password": ADMIN_PASSWORD, "code": next_code(owner, email, secret)},
    )
    assert r.status_code == 200, r.text
    return b


def new_deal_body(role: str = "SELLER", **kw: Any) -> dict[str, Any]:
    return {
        "title": "iPhone 13, 128GB",
        "description": "Цэвэрхэн, баталгаатай",
        "amount_mnt": 1_250_000,
        "item_type": "PHYSICAL_GOODS",
        "delivery_method": "FACE_TO_FACE",
        "inspection_days": 3,
        "my_role": role,
        **kw,
    }
