"""Application settings loaded from environment variables.

Secrets are never hard-coded; see the repository-level ``.env.example``.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Reads apps/api/.env or the repository-root .env when run from apps/api.
    model_config = SettingsConfigDict(env_file=(".env", "../../.env"), extra="ignore")

    app_env: Literal["local", "test", "staging", "production"] = "local"
    app_name: str = "SafePay API"
    app_version: str = "0.1.0"

    # Must use the psycopg 3 driver, e.g. postgresql+psycopg://user:pass@host:5432/db
    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+psycopg://safepay:safepay@localhost:5432/safepay"),
    )
    db_pool_size: int = 5
    db_pool_timeout_seconds: int = 5
    readiness_db_timeout_ms: int = 2000

    cors_allowed_origins: list[str] = ["http://localhost:3000"]

    # Hard safety switch: SafePay Beta must never move real money. Any value
    # other than true is rejected at startup.
    payments_simulation_only: bool = True

    @field_validator("payments_simulation_only")
    @classmethod
    def _must_be_simulation_only(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("PAYMENTS_SIMULATION_ONLY must be true (no real money, ever)")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
