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
    # Comma-separated. Browsers treat http://127.0.0.1:3000 and http://localhost:3000 as different origins.
    api_cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    web_public_url: str = "http://localhost:3000"

    database_url: str = Field(
        default="postgresql+asyncpg://shiftops:shiftops@postgres:5432/shiftops",
        description="Runtime async pool. Supabase: use transaction pooler :6543 (postgresql+asyncpg).",
    )
    database_url_sync: str = Field(
        default="postgresql+psycopg://shiftops:shiftops@postgres:5432/shiftops",
        description="Sync URL for Alembic/psycopg. Supabase: session pooler :5432 (DEPLOY.md).",
    )
    # If the session pooler returns FATAL: Tenant or user not found, set this to the
    # *Direct connection* URI from Supabase (Project Settings -> Database) with
    # postgresql+psycopg:// — often works when pooler user sync is broken.
    alembic_database_url: str | None = Field(
        default=None,
        description="Optional Alembic-only DSN. Env: ALEMBIC_DATABASE_URL. Overrides database_url_sync.",
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
    # When True, asyncpg always uses ``statement_cache_size=0`` (required for
    # PgBouncer transaction pooler). Auto-detection from ``database_url``
    # (port 6543 / host contains ``pooler``) is the default; set this if your
    # DSN still hits DuplicatePreparedStatementError on Fly/Supabase.
    db_disable_asyncpg_statement_cache: bool = False

    database_rls_bypass_role: str = Field(
        default="shiftops_rls_bypass",
        description=(
            "NOLOGIN BYPASSRLS role used with SET LOCAL ROLE in enter_privileged_rls_mode. "
            "Grant membership to the runtime DB user after migrations."
        ),
    )

    redis_url: str = "redis://redis:6379/0"

    jwt_secret: SecretStr = Field(default=SecretStr("change-me-to-32-chars-min-secret-please"))
    jwt_access_ttl_seconds: int = 900
    jwt_refresh_ttl_seconds: int = 604_800

    tg_bot_token: SecretStr = Field(default=SecretStr(""))
    tg_bot_username: str = "ShiftOpsBot"
    # Optional platform operator: when set, /create_org in the bot is enabled
    # for this numeric Telegram user id. Alternative long-term: a system_admin
    # row in DB; for now env-based is enough and keeps migrations out of pilot.
    super_admin_tg_id: int | None = None
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
    # Grayscale mean (0–255) below this marks a photo as suspiciously dark (lens covered / black frame).
    antifake_min_mean_luminance_255: float = Field(default=14.0, ge=1.0, le=254.0)

    # Soft-deleted organizations are hard-deleted after this many days.
    org_deletion_retention_days: int = Field(default=30, ge=1, le=365)
    # If TWA sends geolocation on shift start and it is farther than this from ``locations.geo``, we log audit.
    shift_start_geo_warn_radius_m: float = Field(default=400.0, ge=50.0, le=50_000.0)

    # SLA threshold for the analytics dashboard's "late start" tile.
    # A shift counts as "late" when ``actual_start - scheduled_start`` is
    # greater than this many minutes. Aligned with the operator-side T-30
    # reminder cron: anything bigger than 15 minutes past the scheduled
    # start is a real lateness, not a clock-skew false positive.
    analytics_sla_late_start_min: int = 15

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
