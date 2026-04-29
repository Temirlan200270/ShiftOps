"""Team snapshot & admin actions."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser, require_role, require_user
from shiftops_api.application.team.change_member_role import (
    ChangeMemberRoleUseCase,
    evaluate_role_change_eligibility,
)
from shiftops_api.application.team.deactivate_member import (
    DeactivateMemberUseCase,
    evaluate_deactivation_eligibility,
)
from shiftops_api.application.team.permissions import is_platform_super_admin
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import Failure, Success
from shiftops_api.infra.db.engine import get_session
from shiftops_api.infra.db.models import TelegramAccount, User

router = APIRouter()

_view_team = require_role(UserRole.ADMIN, UserRole.OWNER)


async def _require_manager(current: CurrentUser = Depends(require_user)) -> CurrentUser:
    """Allow only org owner or platform super-admin to manage team members."""
    if current.role == UserRole.OWNER or is_platform_super_admin(current):
        return current
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="insufficient_role",
    )


class TeamSummaryOut(BaseModel):
    other_members_count: int = Field(
        description="Users in the org other than the current user (0 = you are alone in the team)"
    )
    org_total_members: int = Field(
        description="All active seats in the organization, including the current user"
    )


class TeamMemberOut(BaseModel):
    """One org member plus action eligibility for admin UI."""

    id: uuid.UUID
    full_name: str
    role: str
    is_active: bool
    tg_user_id: int | None = Field(default=None)
    tg_username: str | None = None
    can_deactivate: bool
    cannot_deactivate_reason: str | None = Field(
        default=None,
        description="Stable code when can_deactivate is false (insufficient_role, …)",
    )
    can_change_role: bool
    cannot_change_role_reason: str | None = Field(
        default=None,
        description="Stable code when can_change_role is false (cannot_change_owner_role, …)",
    )


class ChangeMemberRoleIn(BaseModel):
    role: Literal["admin", "operator", "bartender"]


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


@router.get(
    "/members",
    response_model=list[TeamMemberOut],
    summary="List organization members (admin/owner)",
)
async def list_team_members(
    session: AsyncSession = Depends(get_session),
    current: CurrentUser = Depends(_view_team),
    include_inactive: bool = False,
) -> list[TeamMemberOut]:
    stmt = (
        select(User, TelegramAccount.tg_user_id, TelegramAccount.tg_username)
        .outerjoin(TelegramAccount, TelegramAccount.user_id == User.id)
        .where(User.organization_id == current.organization_id)
    )
    if not include_inactive:
        stmt = stmt.where(User.is_active.is_(True))
    stmt = stmt.order_by(User.full_name.asc(), User.role.asc())

    rows = (await session.execute(stmt)).all()
    result: list[TeamMemberOut] = []
    for row in rows:
        u, tg_id, tg_username = row[0], row[1], row[2]
        can_deact, deact_reason = await evaluate_deactivation_eligibility(
            actor=current, target=u, session=session
        )
        can_role, role_reason = await evaluate_role_change_eligibility(
            actor=current, target=u, session=session
        )
        result.append(
            TeamMemberOut(
                id=u.id,
                full_name=u.full_name,
                role=u.role,
                is_active=u.is_active,
                tg_user_id=int(tg_id) if tg_id is not None else None,
                tg_username=tg_username,
                can_deactivate=can_deact,
                cannot_deactivate_reason=None if can_deact else deact_reason,
                can_change_role=can_role,
                cannot_change_role_reason=None if can_role else role_reason,
            )
        )
    return result


def _http_for_code(code: str) -> int:
    if code == "user_not_found":
        return status.HTTP_404_NOT_FOUND
    if code in {
        "insufficient_role",
        "cannot_manage_self",
        "cannot_manage_super_admin",
        "cannot_change_owner_role",
    }:
        return status.HTTP_403_FORBIDDEN
    return status.HTTP_400_BAD_REQUEST


@router.post(
    "/members/{user_id}/deactivate",
    summary="Soft-delete (deactivate) a member (owner / super-admin)",
)
async def deactivate_member(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current: CurrentUser = Depends(_require_manager),
) -> dict[str, str]:
    uc = DeactivateMemberUseCase(session)
    result = await uc.execute(actor=current, target_user_id=user_id)
    if isinstance(result, Failure):
        code = result.error.code
        raise HTTPException(
            status_code=_http_for_code(code), detail=f"{code}: {result.error.message}"
        )
    assert isinstance(result, Success)
    await session.commit()
    return {"ok": "true"}


@router.post(
    "/members/{user_id}/role",
    summary="Change member role between admin/operator (owner / super-admin)",
)
async def change_member_role(
    user_id: uuid.UUID,
    payload: ChangeMemberRoleIn,
    session: AsyncSession = Depends(get_session),
    current: CurrentUser = Depends(_require_manager),
) -> dict[str, str]:
    uc = ChangeMemberRoleUseCase(session)
    result = await uc.execute(
        actor=current,
        target_user_id=user_id,
        new_role=payload.role,
    )
    if isinstance(result, Failure):
        code = result.error.code
        raise HTTPException(
            status_code=_http_for_code(code), detail=f"{code}: {result.error.message}"
        )
    assert isinstance(result, Success)
    await session.commit()
    return {"ok": "true", "role": result.value.role}
