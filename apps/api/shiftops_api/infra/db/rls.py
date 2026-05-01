"""Helpers for tenant RLS context (GUC) and controlled bypass.

We use Postgres Row Level Security (RLS) with `app.org_id` set per request.
Keeping the `set_config()` call in one place reduces footguns where code
forgets to set the tenant and silently sees "zero rows".

Under ``FORCE ROW LEVEL SECURITY``, table owners no longer bypass policies.
Cross-tenant flows (auth exchange, bot admin, recurring tick) must call
:func:`enter_privileged_rls_mode`.

Why not ``SET LOCAL row_security = off``? For ordinary roles PostgreSQL treats
``row_security=off`` as *fail* any statement that would apply an RLS policy
(pg_dump uses this). It does **not** skip policies. We switch ``current_role``
to a NOLOGIN ``BYPASSRLS`` role (see migration ``0010_rls_bypass_role``).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.config import get_settings
from shiftops_api.infra.metrics import (
    PRIVILEGED_RLS_BYPASS_TOTAL,
    PRIVILEGED_RLS_UNAVAILABLE_TOTAL,
)

_log = structlog.get_logger("shiftops.rls")

_SAFE_PG_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


async def set_org_guc(session: AsyncSession, *, organization_id: uuid.UUID) -> None:
    """Set the RLS tenant context for the current transaction."""

    await session.execute(
        text("SELECT set_config('app.org_id', :org_id, true)"),
        {"org_id": str(organization_id)},
    )


def _validated_bypass_role(name: str) -> str:
    if not _SAFE_PG_IDENT.fullmatch(name):
        msg = "database_rls_bypass_role must be a simple lowercase PostgreSQL identifier"
        raise ValueError(msg)
    return name


class PrivilegedRlsUnavailable(RuntimeError):
    """Raised when the runtime DB user cannot assume the BYPASSRLS helper role."""


async def enter_privileged_rls_mode(session: AsyncSession, *, reason: str) -> None:
    """Assume the BYPASSRLS role until end of transaction (``SET LOCAL ROLE``).

    ``reason`` must be a low-cardinality label (metrics + logs). Use stable
    snake_case strings defined at call sites (e.g. ``exchange_init_data``).
    """

    PRIVILEGED_RLS_BYPASS_TOTAL.labels(reason=reason).inc()
    _log.info("rls.privileged_enter", reason=reason)
    role = _validated_bypass_role(get_settings().database_rls_bypass_role)
    try:
        await session.execute(text(f"SET LOCAL ROLE {role}"))
    except DBAPIError as exc:
        # Most common causes:
        # - migration 0010 not applied (role doesn't exist)
        # - missing GRANT shiftops_rls_bypass TO <runtime_user>
        # - ALEMBIC_DATABASE_URL used a different role than DATABASE_URL (0012 fixes pooler names)
        PRIVILEGED_RLS_UNAVAILABLE_TOTAL.labels(reason=reason).inc()
        db_user: str | None = None
        try:
            await session.rollback()
            db_user = await session.scalar(text("SELECT current_user::text"))
        except Exception:  # noqa: BLE001 — best-effort for ops logs only
            pass
        _log.error(
            "rls.privileged_unavailable",
            reason=reason,
            role=role,
            db_user=db_user,
            error=str(getattr(exc, "orig", exc)),
        )
        raise PrivilegedRlsUnavailable(
            f"privileged_rls_unavailable: cannot SET LOCAL ROLE {role}"
        ) from exc


@asynccontextmanager
async def privileged_rls(session: AsyncSession, *, reason: str) -> AsyncIterator[None]:
    """Context manager wrapping :func:`enter_privileged_rls_mode` for short
    privileged blocks."""

    await enter_privileged_rls_mode(session, reason=reason)
    yield


__all__ = [
    "PrivilegedRlsUnavailable",
    "enter_privileged_rls_mode",
    "privileged_rls",
    "set_org_guc",
]
