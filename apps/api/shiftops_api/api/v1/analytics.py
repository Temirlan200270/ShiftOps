"""Analytics HTTP endpoints — admin and owner only.

Why one ``/overview`` endpoint instead of one per chart
-------------------------------------------------------
The screen renders four cards from the same time window. Splitting
into four endpoints would multiply Supabase pooler latency by 4 for no
caching win. The aggregate query set still returns under ~80 ms on
30 days of pilot data on the free tier.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.analytics.overview import (
    AnalyticsOverviewUseCase,
    DEFAULT_DAYS,
    MAX_DAYS,
)
from shiftops_api.application.auth.deps import CurrentUser, require_role
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import Failure, Success
from shiftops_api.infra.db.engine import get_session

router = APIRouter()

_admin_or_owner = require_role(UserRole.ADMIN, UserRole.OWNER)


class KpiBlockOut(BaseModel):
    shifts_closed: int
    shifts_clean: int
    shifts_with_violations: int
    average_score: float | None
    cleanliness_rate: float | None


class HeatmapCellOut(BaseModel):
    day_of_week: int
    hour_of_day: int
    shift_count: int
    average_score: float | None


class ViolatorRowOut(BaseModel):
    user_id: UUID
    full_name: str
    shifts_total: int
    shifts_with_violations: int
    average_score: float | None


class LocationRowOut(BaseModel):
    location_id: UUID
    location_name: str
    shifts_total: int
    shifts_with_violations: int
    average_score: float | None


class OverviewResponse(BaseModel):
    range_from: str
    range_to: str
    days: int
    kpis: KpiBlockOut
    heatmap: list[HeatmapCellOut]
    top_violators: list[ViolatorRowOut]
    locations: list[LocationRowOut]


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    days: Annotated[
        int,
        Query(ge=1, le=MAX_DAYS, description=f"Window in days (default {DEFAULT_DAYS})."),
    ] = DEFAULT_DAYS,
    location_id: Annotated[UUID | None, Query()] = None,
    user: CurrentUser = Depends(_admin_or_owner),
    session: AsyncSession = Depends(get_session),
) -> OverviewResponse:
    use_case = AnalyticsOverviewUseCase(session=session)
    result = await use_case.execute(user=user, days=days, location_id=location_id)
    if isinstance(result, Failure):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=result.error.code,
        )
    assert isinstance(result, Success)
    dto = result.value

    return OverviewResponse(
        range_from=dto.range_from.isoformat(),
        range_to=dto.range_to.isoformat(),
        days=days,
        kpis=KpiBlockOut(
            shifts_closed=dto.kpis.shifts_closed,
            shifts_clean=dto.kpis.shifts_clean,
            shifts_with_violations=dto.kpis.shifts_with_violations,
            average_score=(
                float(dto.kpis.average_score) if dto.kpis.average_score is not None else None
            ),
            cleanliness_rate=(
                float(dto.kpis.cleanliness_rate)
                if dto.kpis.cleanliness_rate is not None
                else None
            ),
        ),
        heatmap=[
            HeatmapCellOut(
                day_of_week=c.day_of_week,
                hour_of_day=c.hour_of_day,
                shift_count=c.shift_count,
                average_score=(
                    float(c.average_score) if c.average_score is not None else None
                ),
            )
            for c in dto.heatmap
        ],
        top_violators=[
            ViolatorRowOut(
                user_id=v.user_id,
                full_name=v.full_name,
                shifts_total=v.shifts_total,
                shifts_with_violations=v.shifts_with_violations,
                average_score=(
                    float(v.average_score) if v.average_score is not None else None
                ),
            )
            for v in dto.top_violators
        ],
        locations=[
            LocationRowOut(
                location_id=loc.location_id,
                location_name=loc.location_name,
                shifts_total=loc.shifts_total,
                shifts_with_violations=loc.shifts_with_violations,
                average_score=(
                    float(loc.average_score) if loc.average_score is not None else None
                ),
            )
            for loc in dto.locations
        ],
    )
