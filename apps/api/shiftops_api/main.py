"""FastAPI application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sentry_sdk
import structlog
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator, metrics
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sqlalchemy import text

from shiftops_api import __version__
from shiftops_api.api.errors import install_error_handlers
from shiftops_api.api.v1.router import api_v1_router
from shiftops_api.config import Settings, get_settings
from shiftops_api.infra.db.engine import dispose_engine, get_sessionmaker
from shiftops_api.infra.logging import configure_logging
from shiftops_api.infra.queue import broker
from shiftops_api.infra.realtime import get_event_bus

# HTTP-latency buckets tuned for a Python service that mostly does
# Postgres pooler round-trips on Supabase free tier. The default
# library buckets are too coarse around the 50–250 ms region where we
# live in steady state.
_HTTP_LATENCY_BUCKETS: tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
)


def _init_sentry() -> None:
    settings = get_settings()
    if not settings.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        release=f"shiftops-api@{__version__}",
        traces_sample_rate=settings.sentry_traces_sample_rate,
        integrations=[
            FastApiIntegration(),
            AsyncioIntegration(),
            SqlalchemyIntegration(),
        ],
    )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    _init_sentry()
    log = structlog.get_logger("shiftops.lifespan")
    log.info("api.startup", version=__version__, env=get_settings().app_env)

    # Start the TaskIQ broker so `.kiq()` calls in request handlers can push
    # to Redis. In worker mode (`taskiq worker ...`) the CLI calls startup
    # itself; in API mode we own the lifecycle. `is_worker_process` flips on
    # under the worker CLI so this is a no-op there.
    if not broker.is_worker_process:
        await broker.startup()
        log.info("taskiq.broker.startup")

    try:
        yield
    finally:
        if not broker.is_worker_process:
            await broker.shutdown()
            log.info("taskiq.broker.shutdown")
        # Close the realtime Redis client. Failure here is non-fatal
        # (the process is going down anyway) so swallow exceptions.
        try:
            await get_event_bus().aclose()
            log.info("realtime.event_bus.shutdown")
        except Exception as exc:  # noqa: BLE001
            log.warning("realtime.event_bus.shutdown_failed", error=str(exc))
        await dispose_engine()
        log.info("api.shutdown")


def apply_cors_middleware(app: FastAPI, settings: Settings) -> None:
    """Attach production CORS policy (tested in `tests/test_cors.py`)."""

    # `API_CORS_ORIGINS` = explicit (prod, custom domain, localhost). Branch /
    # preview Vercel URLs: `allow_origin_regex`. Mobile Telegram WebView often
    # `allow_origin_regex`: Vercel previews/prod on `*.vercel.app`, and any
    # `*.telegram.org` host (oauth / web / desktop clients). Apex `telegram.org`
    # stays in `allow_origins` — it does not match the subdomain regex.
    _tg_embed = ("https://web.telegram.org", "https://telegram.org")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[*settings.cors_origins_list, *_tg_embed],
        allow_origin_regex=r"https://.*\.vercel\.app|https://.*\.telegram\.org",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_private_network=True,
    )


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ShiftOps API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
    )

    apply_cors_middleware(app, settings)

    install_error_handlers(app)
    app.include_router(api_v1_router, prefix="/api/v1")

    # Prometheus instrumentation via prometheus_fastapi_instrumentator.
    # The library handles route-template grouping (so we don't get a
    # series-per-UUID), status-code grouping (2xx/3xx/4xx/5xx), and
    # exposes /metrics for free.
    #
    # Why the explicit `metrics.latency(...)` call: the user-facing
    # name `shiftops_api_latency_seconds` is part of the dashboard
    # contract in `ops/grafana/`. We want it stable, so we override
    # the default `http_request_duration_seconds` once here.
    instrumentator = Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_respect_env_var=False,
        should_instrument_requests_inprogress=True,
        inprogress_name="http_requests_inprogress",
        excluded_handlers=["/metrics", "/healthz", "/readyz"],
    )
    instrumentator.add(
        metrics.latency(
            metric_name="shiftops_api_latency_seconds",
            buckets=_HTTP_LATENCY_BUCKETS,
        )
    )
    instrumentator.add(metrics.requests())
    instrumentator.instrument(app).expose(
        app,
        endpoint="/metrics",
        include_in_schema=False,
        tags=["meta"],
    )

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict[str, str]:
        # Liveness: process is up, asyncio loop responsive. Intentionally
        # touches nothing external so a flaky DB doesn't cause a restart loop.
        return {"status": "ok"}

    @app.get("/readyz", tags=["meta"])
    async def readyz() -> JSONResponse:
        # Readiness: dependencies are reachable and we can serve real traffic.
        # `SELECT 1` is the cheapest possible ping but it does cause Supabase
        # to count us as "active" — used by `.github/workflows/cron-warmup.yml`
        # to keep the free-tier project from auto-pausing.
        log = structlog.get_logger("shiftops.health")
        try:
            factory = get_sessionmaker()
            async with factory() as session:
                await session.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 — surface as 503, not 500
            log.warning("readyz.db_unreachable", error=str(exc))
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready", "reason": "db_unreachable"},
            )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "ready"},
        )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    uvicorn.run("shiftops_api.main:app", host=settings.api_host, port=settings.api_port, reload=True)
