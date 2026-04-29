"""Organization-level settings (business hours) scoped to JWT tenant."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser, require_role
from shiftops_api.application.organizations.business_hours_config import BusinessHoursConfig
from shiftops_api.application.organizations.business_hours_settings import (
    GetBusinessHoursUseCase,
    SaveBusinessHoursUseCase,
)
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import Failure, Success
from shiftops_api.infra.db.engine import get_session

router = APIRouter()

_admin_or_owner = require_role(UserRole.ADMIN, UserRole.OWNER)


@router.get(
    "/business-hours",
    response_model=BusinessHoursConfig,
    summary="Opening hours: recurring weekly + dated overrides",
)
async def get_business_hours(
    session: AsyncSession = Depends(get_session),
    current: CurrentUser = Depends(_admin_or_owner),
) -> BusinessHoursConfig:
    uc = GetBusinessHoursUseCase(session=session)
    return await uc.execute(user=current)


@router.put(
    "/business-hours",
    response_model=BusinessHoursConfig,
    summary="Replace opening hours JSON for the organization",
)
async def put_business_hours(
    body: BusinessHoursConfig,
    session: AsyncSession = Depends(get_session),
    current: CurrentUser = Depends(_admin_or_owner),
) -> BusinessHoursConfig:
    uc = SaveBusinessHoursUseCase(session=session)
    result = await uc.execute(user=current, payload=body)
    if isinstance(result, Failure):
        if result.error.code == "forbidden":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=result.error.code)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{result.error.code}: {result.error.message}",
        )
    assert isinstance(result, Success)
    return await GetBusinessHoursUseCase(session=session).execute(user=current)
