"""Reusable idempotency for operations that must happen at most once.

Protocol (all inside the caller's ``atomic`` transaction):

1. *Claim*: ``INSERT … ON CONFLICT DO NOTHING`` a row for ``(scope, key)``.
   If another transaction holds an uncommitted claim for the same key,
   PostgreSQL makes this INSERT wait until that transaction ends.
2. If we claimed the key, run the operation and store its JSON result in the
   same transaction. Commit makes both visible atomically; a rollback removes
   the claim too, so a failed attempt can be retried with the same key.
3. If the key already exists (committed), compare request fingerprints:
   identical → return the stored result (``replayed=True``) without running the
   operation; different → raise ``IdempotencyKeyReusedError``.

Only *successful* results are stored. A request that fails is not cached; a
retry re-executes it and is re-validated by the database.
"""

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.idempotency import IdempotencyRecord

_KEY_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")


class InvalidIdempotencyKeyError(ValueError):
    pass


class IdempotencyKeyReusedError(Exception):
    """The key was already used for a request with different contents (HTTP 409)."""

    def __init__(self, scope: str, key: str) -> None:
        super().__init__(
            f"idempotency key {key!r} was already used for a different {scope} request"
        )
        self.scope = scope
        self.key = key


@dataclass(frozen=True, slots=True)
class IdempotentResult:
    response: dict[str, Any]
    replayed: bool


def request_fingerprint(request: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON form (sorted keys, no whitespace, UUIDs as str)."""
    canonical = json.dumps(
        request, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def run_idempotent(
    session: Session,
    *,
    scope: str,
    key: str,
    request: Mapping[str, Any],
    operation: Callable[[], dict[str, Any]],
) -> IdempotentResult:
    if not _KEY_RE.fullmatch(key):
        raise InvalidIdempotencyKeyError(
            "idempotency key must be 1-128 characters of A-Z a-z 0-9 . _ : -"
        )
    if not session.in_transaction():
        raise RuntimeError("run_idempotent must be called inside atomic(session)")

    fingerprint = request_fingerprint(request)
    claimed = session.execute(
        insert(IdempotencyRecord)
        .values(scope=scope, key=key, request_hash=fingerprint)
        .on_conflict_do_nothing(index_elements=["scope", "key"])
        .returning(IdempotencyRecord.key)
    ).scalar_one_or_none()

    if claimed is None:
        existing = session.execute(
            select(IdempotencyRecord.request_hash, IdempotencyRecord.response).where(
                IdempotencyRecord.scope == scope, IdempotencyRecord.key == key
            )
        ).one()
        if existing.request_hash != fingerprint:
            raise IdempotencyKeyReusedError(scope, key)
        if existing.response is None:  # pragma: no cover - impossible after the claim wait
            raise RuntimeError("idempotency record committed without a response")
        return IdempotentResult(response=existing.response, replayed=True)

    response = operation()
    session.execute(
        update(IdempotencyRecord)
        .where(IdempotencyRecord.scope == scope, IdempotencyRecord.key == key)
        .values(response=response)
    )
    return IdempotentResult(response=response, replayed=False)
