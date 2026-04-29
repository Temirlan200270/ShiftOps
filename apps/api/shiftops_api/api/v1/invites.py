"""Invite creation — owner/admin; deep links consumed in Telegram bot."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser, require_role
from shiftops_api.application.invites.create_invite import CreateInviteUseCase
from shiftops_api.config import get_settings
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import Failure, Success
from shiftops_api.infra.db.engine import get_session

router = APIRouter()

_inviter = require_role(UserRole.ADMIN, UserRole.OWNER)


class CreateInviteIn(BaseModel):
    role: str = Field(
        min_length=5,
        max_length=16,
        description="admin, operator, or bartender",
    )
    location_id: uuid.UUID | None = None
    expires_in_hours: int | None = Field(default=None, ge=1, le=168)


class CreateInviteOut(BaseModel):
    invite_id: uuid.UUID
    token: str
    deep_link: str
    expires_at: datetime


@router.post(
    "",
    response_model=CreateInviteOut,
    summary="Create a one-time Telegram invite link",
)
async def create_invite(
    body: CreateInviteIn,
    session: AsyncSession = Depends(get_session),
    current: CurrentUser = Depends(_inviter),
) -> CreateInviteOut:
    use_case = CreateInviteUseCase(session)
    result = await use_case.execute(
        user=current,
        role=body.role,
        location_id=body.location_id,
        expires_in_hours=body.expires_in_hours,
    )
    if isinstance(result, Failure):
        code = result.error.code
        status_code = (
            status.HTTP_403_FORBIDDEN
            if code in ("insufficient_role", "invite_admin_requires_owner")
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(
            status_code=status_code,
            detail=f"{code}: {result.error.message}",
        )
    assert isinstance(result, Success)
    settings = get_settings()
    uname = settings.tg_bot_username.lstrip("@")
    # Telegram passes the start payload as a single /start argument.
    deep = f"https://t.me/{uname}?start=inv_{result.value.token}"
    await session.commit()
    return CreateInviteOut(
        invite_id=result.value.id,
        token=result.value.token,
        deep_link=deep,
        expires_at=result.value.expires_at,
    )
