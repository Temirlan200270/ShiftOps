"""Application settings sourced from environment variables.

Centralised so the app never reads `os.environ` directly outside this module.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["local", "staging", "production"] = "local"
    app_name: str = "ShiftOps"
    log_level: str = "INFO"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_public_url: str = "http://localhost:8000"
    api_cors_origins: str = "http://localhost:3000"

    web_public_url: str = "http://localhost:3000"

    database_url: str = Field(
        default="postgresql+asyncpg://shiftops:shiftops@postgres:5432/shiftops",
        description="Runtime async pool. Supabase: use transaction pooler :6543 (postgresql+asyncpg).",
    )
    database_url_sync: str = Field(
        default="postgresql+psycopg://shiftops:shiftops@postgres:5432/shiftops",
        description="Sync URL for Alembic/psycopg. Supabase: use session pooler :5432 or direct db host (DEPLOY.md).",
    )
    # Connection pool sizing is environment-dependent:
    #   - Local Postgres: defaults are fine.
    #   - Supabase free tier (transaction pooler): ceiling is ~60 connections
    #     across the whole project. With one Fly machine running both api +
    #     worker (each gets its own pool) we cap at 5+10 per pool to leave
    #     headroom for migrations and the smoke script.
    db_pool_size: int = 5
    db_pool_max_overflow: int = 10
    db_pool_recycle_seconds: int = 1800

    redis_url: str = "redis://redis:6379/0"

    jwt_secret: SecretStr = Field(default=SecretStr("change-me-to-32-chars-min-secret-please"))
    jwt_access_ttl_seconds: int = 900
    jwt_refresh_ttl_seconds: int = 604_800

    tg_bot_token: SecretStr = Field(default=SecretStr(""))
    tg_bot_username: str = "ShiftOpsBot"
    tg_webhook_secret: SecretStr = Field(default=SecretStr(""))
    tg_webhook_path: str = "/api/v1/telegram/webhook"
    tg_archive_chat_id: int | None = None

    storage_provider: Literal["telegram", "r2"] = "telegram"

    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: SecretStr = Field(default=SecretStr(""))
    r2_bucket: str = ""
    r2_public_url: str = ""

    antifake_phash_threshold: int = 5
    antifake_history_lookback: int = 50

    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.1

    feature_offline_queue: bool = True
    feature_analytics_dashboard: bool = False
    feature_billing: bool = False

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor. Use this everywhere."""
    return Settings()
