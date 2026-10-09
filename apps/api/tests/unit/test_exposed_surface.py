"""Trust boundary guard: no HTTP route may reach money movement in Phase 1A.

``transition_deal`` trusts the ``actor`` / ``actor_user_id`` it is given (the
database verifies participation, not identity). Until authentication exists
(Phase 1B), exposing it over HTTP would allow actor impersonation and
unauthorized ADMIN/SYSTEM operations. These tests make adding any new route,
or wiring the service into the HTTP layer, a deliberate, reviewed change.
"""

import ast
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.main import create_app

API_PACKAGE = Path(__file__).resolve().parents[2] / "app" / "api"

ALLOWED_ROUTES = {
    ("GET", "/health"),
    ("GET", "/ready"),
    # FastAPI's own documentation routes (disabled when APP_ENV=production).
    ("GET", "/openapi.json"),
    ("GET", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
}


def _walk(routes: Iterable[Any], prefix: str = "") -> set[tuple[str, str]]:
    """Collect (method, path) for every route, including nested routers.

    Fails closed: if FastAPI's internals change so that routes cannot be found,
    the result no longer equals the allow-list and the test fails.
    """
    found: set[tuple[str, str]] = set()
    for route in routes:
        nested = getattr(route, "original_router", None) or getattr(route, "app", None)
        if hasattr(route, "methods") and hasattr(route, "path"):
            found |= {(m, prefix + route.path) for m in route.methods if m != "HEAD"}
        elif nested is not None and hasattr(nested, "routes"):
            context = getattr(route, "include_context", None)
            found |= _walk(nested.routes, prefix + getattr(context, "prefix", ""))
        else:  # unknown route type: refuse to guess
            found.add(("UNKNOWN", repr(route)))
    return found


def test_only_health_routes_are_exposed() -> None:
    assert _walk(create_app().routes) == ALLOWED_ROUTES


def test_openapi_lists_only_health_operations() -> None:
    paths = create_app().openapi()["paths"]
    assert {(m.upper(), p) for p, ops in paths.items() for m in ops} == {
        ("GET", "/health"),
        ("GET", "/ready"),
    }


def test_http_layer_does_not_import_money_movement() -> None:
    for module in [*API_PACKAGE.glob("*.py"), API_PACKAGE.parent / "main.py"]:
        tree = ast.parse(module.read_text())
        imported = {
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert not any(name.startswith("app.services") for name in imported), module
