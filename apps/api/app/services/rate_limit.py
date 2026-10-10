"""DB-backed fixed-window rate limiting (works across processes and restarts).

Counters are committed in their own short transaction, so a request that later
fails still counts against the limit.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine, text

from app.core.security import sha256_hex


@dataclass(frozen=True, slots=True)
class Limit:
    bucket: str
    max_hits: int
    window_seconds: int


LOGIN_PER_IP = Limit("login:ip", 30, 900)
LOGIN_PER_EMAIL = Limit("login:email", 10, 900)
REGISTER_PER_IP = Limit("register:ip", 10, 3600)
EMAIL_ACTION_PER_EMAIL = Limit("email:target", 3, 3600)
EMAIL_ACTION_PER_IP = Limit("email:ip", 20, 3600)
TOKEN_ATTEMPT_PER_IP = Limit("token:ip", 30, 900)
MUTATION_PER_USER = Limit("mutation:user", 120, 60)
EVIDENCE_PER_USER = Limit("evidence:user", 30, 3600)
PROFILE_PER_USER = Limit("profile:user", 10, 3600)
ADMIN_LOGIN_PER_IP = Limit("admin-login:ip", 10, 900)
ADMIN_LOGIN_PER_EMAIL = Limit("admin-login:email", 5, 900)


class RateLimitedError(Exception):
    def __init__(self, limit: Limit) -> None:
        super().__init__(f"rate limit {limit.bucket} exceeded")
        self.limit = limit


def hit(engine: Engine, limit: Limit, key: str) -> None:
    """Count one hit; raise RateLimitedError when the window's budget is exceeded."""
    now = datetime.now(UTC).timestamp()
    window = datetime.fromtimestamp(now - now % limit.window_seconds, UTC)
    with engine.begin() as conn:
        count = conn.execute(
            text(
                "INSERT INTO rate_limits (bucket, key_hash, window_start, count) "
                "VALUES (:b, :k, :w, 1) "
                "ON CONFLICT (bucket, key_hash, window_start) "
                "DO UPDATE SET count = rate_limits.count + 1 RETURNING count"
            ),
            {"b": limit.bucket, "k": sha256_hex(key.lower()), "w": window},
        ).scalar_one()
    if count > limit.max_hits:
        raise RateLimitedError(limit)
