"""Sentry initialisation shared by all three processes (api, worker, scheduler).

Called from:
  - ``shiftops_api.main`` (FastAPI lifespan) — adds FastAPI/SQLAlchemy integrations.
  - ``shiftops_api.infra.queue`` (module level) — covers worker + scheduler processes.

``sentry_sdk.init()`` is safe to call multiple times; the second call in the
API process simply re-applies settings with the richer integration list.
"""

from __future__ import annotations

import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

from shiftops_api.config import get_settings


def init_sentry(extra_integrations: list | None = None) -> None:
    settings = get_settings()
    if not settings.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        release=f"shiftops-api@{settings.app_env}",
        traces_sample_rate=settings.sentry_traces_sample_rate,
        integrations=[
            AsyncioIntegration(),
            LoggingIntegration(level=None, event_level="ERROR"),
            *(extra_integrations or []),
        ],
    )
