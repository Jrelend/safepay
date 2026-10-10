"""Trust-boundary guards for the HTTP surface.

* The public API exposes exactly the reviewed allow-list and NO admin routes.
* The admin API (separate process, safepay_admin role) exposes only admin routes.
* No route accepts an actor, user id or role from the client: identity is
  derived from the server-side session only.
* The dev mailbox exists only in local/test with an explicit flag.

Adding a route means updating these lists in a reviewed change.
"""

import ast
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.main import create_app

API_PACKAGE = Path(__file__).resolve().parents[2] / "app" / "api"

DOCS = {("GET", "/openapi.json"), ("GET", "/docs"), ("GET", "/docs/oauth2-redirect")}
HEALTH = {("GET", "/health"), ("GET", "/ready")}

PUBLIC_ROUTES = (
    HEALTH
    | DOCS
    | {
        ("POST", "/auth/register"),
        ("POST", "/auth/verify-email"),
        ("POST", "/auth/resend-verification"),
        ("POST", "/auth/login"),
        ("POST", "/auth/logout"),
        ("POST", "/auth/password-reset/request"),
        ("POST", "/auth/password-reset/confirm"),
        ("POST", "/auth/password/change"),
        ("GET", "/auth/me"),
        ("GET", "/auth/sessions"),
        ("DELETE", "/auth/sessions/{session_id}"),
        ("POST", "/auth/sessions/revoke-others"),
        ("PATCH", "/me/profile"),
        ("GET", "/me/notifications"),
        ("POST", "/me/notifications/read-all"),
        ("GET", "/me/wallet"),
        ("POST", "/deals"),
        ("GET", "/deals"),
        ("GET", "/deals/{deal_id}"),
        ("PATCH", "/deals/{deal_id}"),
        ("POST", "/deals/{deal_id}/invite"),
        ("POST", "/deals/{deal_id}/actions"),
        ("GET", "/deals/{deal_id}/timeline"),
        ("GET", "/deals/{deal_id}/escrow"),
        ("GET", "/invites/{token}"),
        ("POST", "/invites/{token}/join"),
        ("GET", "/disputes/{dispute_id}"),
        ("POST", "/disputes/{dispute_id}/statements"),
        ("POST", "/disputes/{dispute_id}/files"),
        ("GET", "/disputes/{dispute_id}/evidence/{evidence_id}/file"),
    }
)

ADMIN_ROUTES = (
    HEALTH
    | DOCS
    | {
        ("POST", "/admin/auth/login"),
        ("POST", "/admin/auth/logout"),
        ("GET", "/admin/auth/me"),
        ("GET", "/admin/overview"),
        ("GET", "/admin/disputes"),
        ("GET", "/admin/disputes/{dispute_id}"),
        ("GET", "/admin/disputes/{dispute_id}/evidence/{evidence_id}/file"),
        ("POST", "/admin/disputes/{dispute_id}/notes"),
        ("POST", "/admin/disputes/{dispute_id}/decision"),
        ("GET", "/admin/users"),
        ("POST", "/admin/users/{user_id}/status"),
        ("GET", "/admin/audit"),
    }
)

# Names a client could use to claim an identity or privilege.
FORBIDDEN_INPUTS = {"actor", "actor_type", "actor_user_id", "user_id", "role", "is_admin", "admin"}


def _walk(routes: Iterable[Any], prefix: str = "") -> set[tuple[str, str]]:
    """Fails closed: unknown route types are reported, not ignored."""
    found: set[tuple[str, str]] = set()
    for route in routes:
        nested = getattr(route, "original_router", None) or getattr(route, "app", None)
        if hasattr(route, "methods") and hasattr(route, "path"):
            found |= {(m, prefix + route.path) for m in route.methods if m != "HEAD"}
        elif nested is not None and hasattr(nested, "routes"):
            context = getattr(route, "include_context", None)
            found |= _walk(nested.routes, prefix + getattr(context, "prefix", ""))
        else:
            found.add(("UNKNOWN", repr(route)))
    return found


def _settings(**overrides: Any) -> Settings:
    # Ignore any developer .env: the surface must be judged on explicit settings only.
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_public_api_surface_is_exactly_the_allow_list() -> None:
    assert _walk(create_app(_settings(api_mode="public")).routes) == PUBLIC_ROUTES


def test_admin_api_surface_is_exactly_the_allow_list() -> None:
    assert _walk(create_app(_settings(api_mode="admin")).routes) == ADMIN_ROUTES


def test_public_api_has_no_admin_routes_and_vice_versa() -> None:
    public = {p for _, p in _walk(create_app(_settings(api_mode="public")).routes)}
    admin = {p for _, p in _walk(create_app(_settings(api_mode="admin")).routes)}
    assert not any(p.startswith("/admin") for p in public)
    assert not any(p.startswith(("/deals", "/invites", "/auth/login")) for p in admin)


def _input_names(schema: dict[str, Any], openapi: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    if "$ref" in schema:
        ref = schema["$ref"].rsplit("/", 1)[-1]
        schema = openapi["components"]["schemas"][ref]
    for name, sub in schema.get("properties", {}).items():
        names.add(name)
        names |= _input_names(sub, openapi)
    for key in ("anyOf", "allOf", "oneOf"):
        for sub in schema.get(key, []):
            names |= _input_names(sub, openapi)
    return names


@pytest.mark.parametrize("mode", ["public", "admin"])
def test_no_route_accepts_identity_or_privilege_from_the_client(mode: str) -> None:
    openapi = create_app(_settings(api_mode=mode)).openapi()
    offenders = []
    for path, ops in openapi["paths"].items():
        for method, op in ops.items():
            names = {p["name"] for p in op.get("parameters", [])}
            for content in op.get("requestBody", {}).get("content", {}).values():
                names |= _input_names(content.get("schema", {}), openapi)
            bad = names & FORBIDDEN_INPUTS
            # /admin/users/{user_id} names the TARGET user in the path, not the actor.
            if path == "/admin/users/{user_id}/status":
                bad -= {"user_id"}
            if bad:
                offenders.append((method.upper(), path, sorted(bad)))
    assert offenders == []


def test_dev_mailbox_requires_local_env_and_flag() -> None:
    def has_mailbox(**kw: Any) -> bool:
        return ("GET", "/dev/mailbox") in _walk(create_app(_settings(**kw)).routes)

    assert not has_mailbox(app_env="local")
    assert has_mailbox(app_env="local", dev_mailbox_enabled=True)
    # Deployed environments refuse to even start with the mailbox flag on.
    for env in ("production", "staging"):
        with pytest.raises(ValueError, match="DEV_MAILBOX_ENABLED must be false"):
            _settings(app_env=env, dev_mailbox_enabled=True)


def test_http_layer_never_calls_system_or_admin_db_functions_from_public_routes() -> None:
    public_modules = ["routes_auth.py", "routes_deals.py", "routes_disputes.py", "routes_me.py"]
    forbidden = {
        "system_transition",
        "admin_refund",
        "admin_resolve_dispute",
        "admin_set_user_status",
    }
    for name in public_modules:
        tree = ast.parse((API_PACKAGE / name).read_text())
        used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        used |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert not used & forbidden, name
