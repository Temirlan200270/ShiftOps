"""Team snapshot & admin actions."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser, require_role
from shiftops_api.application.team.deactivate_member import DeactivateMemberUseCase
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import Failure, Success
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


@router.post(
    "/members/{user_id}/deactivate",
    summary="Soft-delete (deactivate) a member (admin/owner)",
)
async def deactivate_member(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current: CurrentUser = Depends(_view_team),
) -> dict[str, str]:
    uc = DeactivateMemberUseCase(session)
    result = await uc.execute(actor=current, target_user_id=user_id)
    if isinstance(result, Failure):
        code = result.error.code
        status_code = (
            status.HTTP_404_NOT_FOUND
            if code == "user_not_found"
            else status.HTTP_403_FORBIDDEN
            if code in ("insufficient_role", "cannot_deactivate_super_admin")
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=f"{code}: {result.error.message}")
    assert isinstance(result, Success)
    await session.commit()
    return {"ok": "true"}
