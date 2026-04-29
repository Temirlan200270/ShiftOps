"""Audit trail endpoints (read-only, owner/admin).

This is intentionally minimal: a lightweight UI can show recent changes
without building a full analytics product.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser, require_role
from shiftops_api.domain.enums import UserRole
from shiftops_api.infra.db.engine import get_session
from shiftops_api.infra.db.models import AuditEvent, User

router = APIRouter()

_view_audit = require_role(UserRole.ADMIN, UserRole.OWNER)

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 30


class AuditEventOut(BaseModel):
    id: uuid.UUID
    created_at: datetime = Field(description="UTC timestamp")
    event_type: str
    actor_user_id: uuid.UUID | None
    actor_name: str | None
    payload: dict[str, object]


class AuditPageOut(BaseModel):
    items: list[AuditEventOut]
    next_cursor: datetime | None = Field(
        default=None, description="Pass as ?cursor= on the next page request"
    )


@router.get(
    "/events",
    response_model=AuditPageOut,
    summary="Recent audit events for the organization (admin/owner)",
)
async def list_audit_events(
    cursor: datetime | None = Query(
        default=None, description="ISO timestamp from next_cursor of a previous response"
    ),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    event_type: str | None = Query(default=None, description="Optional exact event_type filter"),
    user: CurrentUser = Depends(_view_audit),
    session: AsyncSession = Depends(get_session),
) -> AuditPageOut:
    stmt = (
        select(
            AuditEvent.id,
            AuditEvent.created_at,
            AuditEvent.event_type,
            AuditEvent.actor_user_id,
            User.full_name,
            AuditEvent.payload,
        )
        .outerjoin(User, User.id == AuditEvent.actor_user_id)
        .where(AuditEvent.organization_id == user.organization_id)
    )
    if cursor is not None:
        # Keyset pagination (DESC): fetch items strictly older than cursor.
        stmt = stmt.where(AuditEvent.created_at < cursor)
    if event_type is not None:
        stmt = stmt.where(AuditEvent.event_type == event_type)

    rows = (
        await session.execute(stmt.order_by(desc(AuditEvent.created_at)).limit(limit + 1))
    ).all()

    items_raw = rows[:limit]
    next_cursor = items_raw[-1][1] if len(rows) > limit and items_raw else None

    items = [
        AuditEventOut(
            id=row[0],
            created_at=row[1].astimezone(UTC),
            event_type=row[2],
            actor_user_id=row[3],
            actor_name=row[4],
            payload=row[5] or {},
        )
        for row in items_raw
    ]
    return AuditPageOut(items=items, next_cursor=next_cursor)

