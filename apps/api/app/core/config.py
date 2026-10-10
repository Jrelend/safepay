"""Application settings loaded from environment variables.

Secrets are never hard-coded; see the repository-level ``.env.example``.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Reads apps/api/.env or the repository-root .env when run from apps/api.
    model_config = SettingsConfigDict(env_file=(".env", "../../.env"), extra="ignore")

    app_env: Literal["local", "test", "staging", "production"] = "local"
    app_name: str = "SafePay API"
    app_version: str = "0.1.0"

    # Runtime connection, as the least-privileged ``safepay_app`` role.
    # Must use the psycopg 3 driver, e.g. postgresql+psycopg://user:pass@host:5432/db
    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+psycopg://safepay_app:safepay_app@localhost:5432/safepay"),
    )
    # Used only by Alembic, as the schema-owning ``safepay_migrator`` role.
    # Falls back to DATABASE_URL when unset (the migration then refuses to run
    # unless that role owns the schema; see migration 0002).
    migration_database_url: PostgresDsn | None = None
    db_pool_size: int = 5
    db_pool_timeout_seconds: int = 5
    readiness_db_timeout_ms: int = 2000

    # Browser origins allowed to make state-changing requests (checked on every
    # unsafe request) and to use CORS. The web app proxies /api, so normally
    # this is just the web origin.
    cors_allowed_origins: list[str] = ["http://localhost:3000"]

    # "public" serves the user-facing API as safepay_app; "admin" serves the
    # admin API as safepay_admin. They run as separate processes/containers.
    api_mode: Literal["public", "admin"] = "public"
    # Base URL of the web app, used in (simulated) emails and invite links.
    public_web_url: str = "http://localhost:3000"

    session_ttl_hours: int = Field(default=168, ge=1, le=720)
    session_idle_hours: int = Field(default=24, ge=1, le=168)
    # None = secure cookies everywhere except local/test.
    cookie_secure: bool | None = None
    # Only honour X-Forwarded-For when the API sits behind the trusted web proxy.
    trust_proxy_headers: bool = False

    # Dev-only mailbox endpoint that reveals simulated emails (verification and
    # reset links). Ignored unless APP_ENV is local or test.
    dev_mailbox_enabled: bool = False

    # Background worker (safepay_system role).
    system_database_url: PostgresDsn | None = None
    admin_session_ttl_hours: int = Field(default=8, ge=1, le=24)
    admin_session_idle_minutes: int = Field(default=30, ge=5, le=240)
    worker_interval_seconds: int = Field(default=60, ge=5, le=3600)
    # Beta v0.1: an expired inspection window never releases escrow by itself. Even if
    # set, the DB still refuses unless platform_policy.auto_release_enabled is true.
    worker_auto_release: bool = False

    # Hard safety switch: SafePay Beta must never move real money. Any value
    # other than true is rejected at startup.
    payments_simulation_only: bool = True
    # The only payment mode that exists. Anything else (e.g. "live") fails at startup.
    payment_mode: Literal["simulation"] = "simulation"

    @field_validator("payments_simulation_only")
    @classmethod
    def _must_be_simulation_only(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("PAYMENTS_SIMULATION_ONLY must be true (no real money, ever)")
        return value

    @model_validator(mode="after")
    def _deployed_environments_are_locked_down(self) -> "Settings":
        """Staging and production refuse to start with development conveniences."""
        if self.app_env not in ("staging", "production"):
            return self
        problems = []
        if self.dev_mailbox_enabled:
            problems.append("DEV_MAILBOX_ENABLED must be false")
        if self.cookie_secure is False:
            problems.append("COOKIE_SECURE must not be false")
        if not self.public_web_url.startswith("https://"):
            problems.append("PUBLIC_WEB_URL must be https://")
        if any(not o.startswith("https://") for o in self.cors_allowed_origins):
            problems.append("CORS_ALLOWED_ORIGINS must all be https://")
        if problems:
            raise ValueError(f"unsafe {self.app_env} configuration: " + "; ".join(problems))
        return self

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.app_env not in ("local", "test")

    @property
    def mailbox_enabled(self) -> bool:
        return self.dev_mailbox_enabled and self.app_env in ("local", "test")


@lru_cache
def get_settings() -> Settings:
    return Settings()
