"""Team snapshot — how many other members are in the org (for TWA empty states)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser, require_role
from shiftops_api.domain.enums import UserRole
from shiftops_api.infra.db.engine import get_session
from shiftops_api.infra.db.models import User

router = APIRouter()

_view_team = require_role(UserRole.ADMIN, UserRole.OWNER)


class TeamSummaryOut(BaseModel):
    other_members_count: int = Field(
        description="Users in the org other than the current user (0 = you are alone in the team)"
    )
    org_total_members: int = Field(
        description="All active seats in the organization, including the current user"
    )


@router.get(
    "/summary",
    response_model=TeamSummaryOut,
    summary="Counts for team / empty-state (admin or owner only)",
)
async def team_summary(
    session: AsyncSession = Depends(get_session),
    current: CurrentUser = Depends(_view_team),
) -> TeamSummaryOut:
    others = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.organization_id == current.organization_id,
            User.id != current.id,
            User.is_active.is_(True),
        )
    )
    total = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.organization_id == current.organization_id,
            User.is_active.is_(True),
        )
    )
    return TeamSummaryOut(
        other_members_count=int(others or 0),
        org_total_members=int(total or 0),
    )
