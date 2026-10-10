"""Uniform error responses: {"error": {"code": ..., "message": ...}}.

Codes are stable identifiers the web app maps to Mongolian messages. Messages
are for developers and never contain secrets or internal SQL.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

log = logging.getLogger("safepay.api")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.status = status
        self.code = code
        self.message = message or code


def _body(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.status)

    @app.exception_handler(OperationalError)
    async def _db_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
        # Database down / unreachable / timed out: a clean, retryable 503 (no details).
        log.warning("database unavailable (%s): %s", type(exc.orig).__name__, request.url.path)
        return JSONResponse(
            _body("service_unavailable", "temporarily unavailable, try again shortly"),
            status_code=503,
            headers={"Retry-After": "5"},
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(_body("internal_error", "unexpected error"), status_code=500)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = sorted({".".join(str(p) for p in e.get("loc", ())[1:]) for e in exc.errors()})
        return JSONResponse(
            _body("validation_error", "invalid fields: " + ", ".join(f for f in fields if f)),
            status_code=422,
        )
