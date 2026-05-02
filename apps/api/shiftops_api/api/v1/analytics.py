"""Analytics HTTP endpoints — admin and owner only.

Why one ``/overview`` endpoint instead of one per chart
-------------------------------------------------------
The screen renders many cards from the same time window. Splitting into
per-card endpoints would multiply Supabase pooler latency for no caching
win. The aggregate query set still returns under ~120 ms on 30 days of
pilot data on the free tier (~9 SELECTs × 10 ms RTT).

Date filter
-----------
``from`` / ``to`` win over ``days`` when both are sent. They are inclusive
ISO dates (interpreted as UTC midnight). When neither is sent we fall back
to ``[now - days, now]`` so legacy callers (and the bot) keep working.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.analytics.overview import (
    DEFAULT_DAYS,
    DEFAULT_VIOLATORS_LIMIT,
    MAX_DAYS,
    MAX_VIOLATORS_LIMIT,
    MIN_VIOLATORS_LIMIT,
    AnalyticsOverviewUseCase,
    OverviewDTO,
)
from shiftops_api.application.auth.deps import CurrentUser, require_role
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import Failure, Success
from shiftops_api.infra.db.engine import get_session

router = APIRouter()

_admin_or_owner = require_role(UserRole.ADMIN, UserRole.OWNER)


# --- Pydantic out-models --------------------------------------------------


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
    role: str
    shifts_total: int
    shifts_with_violations: int
    average_score: float | None


class LocationRowOut(BaseModel):
    location_id: UUID
    location_name: str
    shifts_total: int
    shifts_with_violations: int
    average_score: float | None


class TemplateRowOut(BaseModel):
    template_id: UUID
    template_name: str
    shifts_total: int
    shifts_with_violations: int
    average_score: float | None


class PostRowOut(BaseModel):
    location_id: UUID
    location_name: str
    slot_index: int
    station_label: str | None
    shifts_total: int
    shifts_with_violations: int
    average_score: float | None


class CriticalityRowOut(BaseModel):
    criticality: str
    tasks_total: int
    done: int
    skipped: int
    waiver_rejected: int
    suspicious_attachments: int


class AntifakeOut(BaseModel):
    attachments_total: int
    suspicious_total: int
    suspicious_rate: float | None


class SlaOut(BaseModel):
    threshold_min: int
    shifts_with_actual: int
    late_count: int
    late_rate: float | None
    avg_late_min: float | None


class RoleSplitOut(BaseModel):
    operator: KpiBlockOut
    bartender: KpiBlockOut


class DensityOut(BaseModel):
    kpis: str
    heatmap: str
    violators: str
    templates: str
    posts: str


class OverviewResponse(BaseModel):
    range_from: str
    range_to: str
    days: int
    kpis: KpiBlockOut
    heatmap: list[HeatmapCellOut]
    top_violators: list[ViolatorRowOut]
    locations: list[LocationRowOut]
    templates: list[TemplateRowOut]
    posts: list[PostRowOut]
    criticality: list[CriticalityRowOut]
    antifake: AntifakeOut | None
    sla_late_start: SlaOut | None
    role_split: RoleSplitOut | None
    density: DensityOut | None
    previous: OverviewResponse | None = None


# Allow self-recursion in the response model: previous block has same shape
# but never carries another `previous` (only the top level offers compare).
OverviewResponse.model_rebuild()


# --- Endpoint -------------------------------------------------------------


def _resolve_window(
    *,
    days: int,
    range_from: date | None,
    range_to: date | None,
) -> tuple[datetime, datetime]:
    """Convert query params into a UTC half-open ``[from, to]`` window.

    Why this lives here: the use case takes ``datetime`` objects so it can
    stay UI-agnostic. The HTTP layer is the right place to coerce date
    queries (which pilot owners type as ``2026-04-01``) into timezone-aware
    timestamps. Anyone who wants minute precision can call the use case
    directly from a script.
    """
    if range_from is not None and range_to is not None:
        if range_to < range_from:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_range",
            )
        # Inclusive end-of-day so ?to=2026-04-29 covers all of April 29th.
        rf = datetime.combine(range_from, time.min, tzinfo=UTC)
        rt = datetime.combine(range_to, time.max, tzinfo=UTC)
    else:
        rt = datetime.now(tz=UTC)
        rf = rt - timedelta(days=days)
    if (rt - rf) > timedelta(days=MAX_DAYS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="range_too_large",
        )
    return rf, rt


def _serialise(dto: OverviewDTO) -> OverviewResponse:
    days = max(1, int((dto.range_to - dto.range_from).total_seconds() // 86400) or 1)
    return OverviewResponse(
        range_from=dto.range_from.isoformat(),
        range_to=dto.range_to.isoformat(),
        days=days,
        kpis=KpiBlockOut(
            shifts_closed=dto.kpis.shifts_closed,
            shifts_clean=dto.kpis.shifts_clean,
            shifts_with_violations=dto.kpis.shifts_with_violations,
            average_score=_to_float(dto.kpis.average_score),
            cleanliness_rate=_to_float(dto.kpis.cleanliness_rate),
        ),
        heatmap=[
            HeatmapCellOut(
                day_of_week=c.day_of_week,
                hour_of_day=c.hour_of_day,
                shift_count=c.shift_count,
                average_score=_to_float(c.average_score),
            )
            for c in dto.heatmap
        ],
        top_violators=[
            ViolatorRowOut(
                user_id=v.user_id,
                full_name=v.full_name,
                role=v.role,
                shifts_total=v.shifts_total,
                shifts_with_violations=v.shifts_with_violations,
                average_score=_to_float(v.average_score),
            )
            for v in dto.top_violators
        ],
        locations=[
            LocationRowOut(
                location_id=loc.location_id,
                location_name=loc.location_name,
                shifts_total=loc.shifts_total,
                shifts_with_violations=loc.shifts_with_violations,
                average_score=_to_float(loc.average_score),
            )
            for loc in dto.locations
        ],
        templates=[
            TemplateRowOut(
                template_id=t.template_id,
                template_name=t.template_name,
                shifts_total=t.shifts_total,
                shifts_with_violations=t.shifts_with_violations,
                average_score=_to_float(t.average_score),
            )
            for t in dto.templates
        ],
        posts=[
            PostRowOut(
                location_id=p.location_id,
                location_name=p.location_name,
                slot_index=p.slot_index,
                station_label=p.station_label,
                shifts_total=p.shifts_total,
                shifts_with_violations=p.shifts_with_violations,
                average_score=_to_float(p.average_score),
            )
            for p in dto.posts
        ],
        criticality=[
            CriticalityRowOut(
                criticality=c.criticality,
                tasks_total=c.tasks_total,
                done=c.done,
                skipped=c.skipped,
                waiver_rejected=c.waiver_rejected,
                suspicious_attachments=c.suspicious_attachments,
            )
            for c in dto.criticality
        ],
        antifake=(
            AntifakeOut(
                attachments_total=dto.antifake.attachments_total,
                suspicious_total=dto.antifake.suspicious_total,
                suspicious_rate=_to_float(dto.antifake.suspicious_rate),
            )
            if dto.antifake is not None
            else None
        ),
        sla_late_start=(
            SlaOut(
                threshold_min=dto.sla_late_start.threshold_min,
                shifts_with_actual=dto.sla_late_start.shifts_with_actual,
                late_count=dto.sla_late_start.late_count,
                late_rate=_to_float(dto.sla_late_start.late_rate),
                avg_late_min=_to_float(dto.sla_late_start.avg_late_min),
            )
            if dto.sla_late_start is not None
            else None
        ),
        role_split=(
            RoleSplitOut(
                operator=_kpi_out(dto.role_split.operator),
                bartender=_kpi_out(dto.role_split.bartender),
            )
            if dto.role_split is not None
            else None
        ),
        density=(
            DensityOut(
                kpis=dto.density.kpis,
                heatmap=dto.density.heatmap,
                violators=dto.density.violators,
                templates=dto.density.templates,
                posts=dto.density.posts,
            )
            if dto.density is not None
            else None
        ),
        previous=_serialise(dto.previous) if dto.previous is not None else None,
    )


def _to_float(v: object) -> float | None:
    if v is None:
        return None
    return float(v)  # type: ignore[arg-type]


def _kpi_out(kpi: object) -> KpiBlockOut:  # type: ignore[no-untyped-def]
    return KpiBlockOut(
        shifts_closed=kpi.shifts_closed,
        shifts_clean=kpi.shifts_clean,
        shifts_with_violations=kpi.shifts_with_violations,
        average_score=_to_float(kpi.average_score),
        cleanliness_rate=_to_float(kpi.cleanliness_rate),
    )


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    days: Annotated[
        int,
        Query(ge=1, le=MAX_DAYS, description=f"Window in days (default {DEFAULT_DAYS})."),
    ] = DEFAULT_DAYS,
    range_from: Annotated[
        date | None,
        Query(alias="from", description="Inclusive start date (UTC), ISO format."),
    ] = None,
    range_to: Annotated[
        date | None,
        Query(alias="to", description="Inclusive end date (UTC), ISO format."),
    ] = None,
    compare: Annotated[
        bool,
        Query(description="If true, also returns the previous period of equal length."),
    ] = False,
    violators_limit: Annotated[
        int,
        Query(
            ge=MIN_VIOLATORS_LIMIT,
            le=MAX_VIOLATORS_LIMIT,
            description=f"Top N violators (default {DEFAULT_VIOLATORS_LIMIT}).",
        ),
    ] = DEFAULT_VIOLATORS_LIMIT,
    location_id: Annotated[UUID | None, Query()] = None,
    user: CurrentUser = Depends(_admin_or_owner),
    session: AsyncSession = Depends(get_session),
) -> OverviewResponse:
    rf, rt = _resolve_window(days=days, range_from=range_from, range_to=range_to)

    use_case = AnalyticsOverviewUseCase(session=session)
    result = await use_case.execute(
        user=user,
        range_from=rf,
        range_to=rt,
        location_id=location_id,
        violators_limit=violators_limit,
        compare=compare,
    )
    if isinstance(result, Failure):
        # forbidden | invalid_range | range_too_large
        if result.error.code == "forbidden":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=result.error.code,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.error.code,
        )
    assert isinstance(result, Success)
    return _serialise(result.value)
