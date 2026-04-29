"""Org locations (for invite UI and filters)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser, require_role
from shiftops_api.domain.enums import UserRole
from shiftops_api.infra.db.engine import get_session
from shiftops_api.infra.db.models import Location

router = APIRouter()

_viewer = require_role(UserRole.ADMIN, UserRole.OWNER)


class LocationOut(BaseModel):
    id: uuid.UUID
    name: str
    timezone: str


@router.get(
    "",
    response_model=list[LocationOut],
    summary="List locations in the current organization",
)
async def list_locations(
    session: AsyncSession = Depends(get_session),
    current: CurrentUser = Depends(_viewer),
) -> list[LocationOut]:
    rows = (
        await session.execute(
            select(Location)
            .where(Location.organization_id == current.organization_id)
            .order_by(Location.name.asc())
        )
    ).scalars()
    return [LocationOut(id=row.id, name=row.name, timezone=row.timezone) for row in rows]
