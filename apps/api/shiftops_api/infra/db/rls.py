"""Helpers for tenant RLS context (GUC) and controlled bypass.

We use Postgres Row Level Security (RLS) with `app.org_id` set per request.
Keeping the `set_config()` call in one place reduces footguns where code
forgets to set the tenant and silently sees "zero rows".
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_org_guc(session: AsyncSession, *, organization_id: uuid.UUID) -> None:
    """Set the RLS tenant context for the current transaction."""

    await session.execute(
        text("SELECT set_config('app.org_id', :org_id, true)"),
        {"org_id": str(organization_id)},
    )


async def disable_row_security(session: AsyncSession) -> None:
    """Disable RLS for the current transaction.

    This is required for system-level flows (e.g. Telegram exchange, cron
    sweeps) when FORCE RLS is enabled.
    """

    await session.execute(text("SET LOCAL row_security = off"))


__all__ = ["disable_row_security", "set_org_guc"]

