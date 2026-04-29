"""Helpers for tenant RLS context (GUC) and controlled bypass.

We use Postgres Row Level Security (RLS) with `app.org_id` set per request.
Keeping the `set_config()` call in one place reduces footguns where code
forgets to set the tenant and silently sees "zero rows".

Under ``FORCE ROW LEVEL SECURITY``, table owners no longer bypass policies.
Cross-tenant flows (auth exchange, bot admin, recurring tick) must call
:func:`enter_privileged_rls_mode` — never raw ``SET LOCAL row_security`` in
application code.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.infra.metrics import PRIVILEGED_RLS_BYPASS_TOTAL

_log = structlog.get_logger("shiftops.rls")


async def set_org_guc(session: AsyncSession, *, organization_id: uuid.UUID) -> None:
    """Set the RLS tenant context for the current transaction."""

    await session.execute(
        text("SELECT set_config('app.org_id', :org_id, true)"),
        {"org_id": str(organization_id)},
    )


async def _set_local_row_security_off(session: AsyncSession) -> None:
    await session.execute(text("SET LOCAL row_security = off"))


async def enter_privileged_rls_mode(session: AsyncSession, *, reason: str) -> None:
    """Disable RLS for the remainder of the current transaction.

    ``reason`` must be a low-cardinality label (metrics + logs). Use stable
    snake_case strings defined at call sites (e.g. ``exchange_init_data``).
    """

    PRIVILEGED_RLS_BYPASS_TOTAL.labels(reason=reason).inc()
    _log.info("rls.privileged_enter", reason=reason)
    await _set_local_row_security_off(session)


@asynccontextmanager
async def privileged_rls(session: AsyncSession, *, reason: str) -> AsyncIterator[None]:
    """Context manager wrapping :func:`enter_privileged_rls_mode` for short
    privileged blocks."""

    await enter_privileged_rls_mode(session, reason=reason)
    yield


__all__ = ["enter_privileged_rls_mode", "privileged_rls", "set_org_guc"]
