"""Audit-log helper.

Encapsulates the INSERT into `audit_events` so use-cases don't have to repeat
the 3-line dance. Append-only enforced at the DB level (trigger).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.infra.db.models import AuditEvent


async def write_audit(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    event = AuditEvent(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        payload=payload or {},
    )
    session.add(event)
    await session.flush()
