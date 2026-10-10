import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker

from app.api import errors
from app.api.auth_context import CSRF_HEADER, UNSAFE_METHODS
from app.api.health import router as health_router
from app.core.config import Settings, get_settings
from app.db.session import make_engine

REQUEST_ID_HEADER = "X-Request-ID"
SIMULATION_HEADER = "X-SafePay-Simulation"


access_log = logging.getLogger("safepay.access")
if not logging.getLogger().handlers:  # uvicorn configures only its own loggers
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
_SECRET_SEGMENTS = re.compile(r"(/invites/)[^/]+")


def redact_path(path: str) -> str:
    """Bearer secrets that appear in URL paths are never written to logs."""
    return _SECRET_SEGMENTS.sub(r"\1[redacted]", path)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=logging.INFO)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "SafePay Beta escrow **simulation** API. No real money is ever accepted, "
            "held or transferred."
        ),
        # Interactive docs are disabled in production.
        docs_url=None if settings.app_env == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if settings.app_env == "production" else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Idempotency-Key", CSRF_HEADER, REQUEST_ID_HEADER],
    )
    allowed_origins = {o.rstrip("/") for o in settings.cors_allowed_origins}

    @app.middleware("http")
    async def origin_check(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # CSRF defence for every state-changing request, including login and
        # registration (which have no session yet): the browser-supplied
        # Origin (or Referer) must be one of our own origins.
        if request.method in UNSAFE_METHODS:
            origin = request.headers.get("origin")
            if not origin and (referer := request.headers.get("referer")):
                parts = urlsplit(referer)
                origin = f"{parts.scheme}://{parts.netloc}"
            if not origin or origin.rstrip("/") not in allowed_origins:
                return JSONResponse(
                    {"error": {"code": "origin_rejected", "message": "cross-site request"}},
                    status_code=403,
                )
        return await call_next(request)

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if 0 < len(incoming) <= 64 and incoming.isprintable() else ""
        request_id = request_id or uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.monotonic()
        response = await call_next(request)
        # Our own access log: one line per request with secrets redacted (invite
        # tokens in paths; query strings never logged). Uvicorn's is disabled.
        access_log.info(
            "%s %s %s %.0fms rid=%s",
            request.method,
            redact_path(request.url.path),
            response.status_code,
            (time.monotonic() - started) * 1000,
            request_id,
        )
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[SIMULATION_HEADER] = "true"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    # One engine (one database role) per app instance; see app.db.session.
    engine = make_engine(settings)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    errors.install(app)
    app.include_router(health_router)
    if settings.api_mode == "public":
        from app.api import (  # noqa: PLC0415 - mode-specific wiring
            routes_auth,
            routes_deals,
            routes_disputes,
            routes_me,
        )

        app.include_router(routes_auth.router)
        app.include_router(routes_me.router)
        app.include_router(routes_deals.router)
        app.include_router(routes_disputes.router)
        if settings.mailbox_enabled:
            from app.api import routes_dev  # noqa: PLC0415

            app.include_router(routes_dev.router)
    else:
        from app.api import admin_auth, routes_admin  # noqa: PLC0415

        app.include_router(admin_auth.router)
        app.include_router(routes_admin.router)
    return app


app = create_app()
