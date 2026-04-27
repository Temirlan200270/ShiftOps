"""S9 — Owner / admin overview dashboard.

Returns four data artefacts in one round-trip:

1. **KPIs**: total closed shifts, average score, % shifts closed clean,
   % shifts with at least one critical task missed (always 0 for
   closed shifts because we hard-block; here we use waiver-rejected /
   skipped *required* tasks as the "violation" signal).
2. **Heatmap**: 7×24 (day-of-week × hour-of-day) cells, where each cell
   is the average score of shifts that **scheduled-started** in that
   slot. Empty cells return ``None`` so the UI can render a gap, not a
   fake zero.
3. **Top violators**: top 3 operators ranked by ``shifts_with_violations
   / shifts_total``, ties broken by absolute violations.
4. **Locations breakdown**: per-location counts and avg score so the
   owner spots the underperforming location at a glance.

Day-of-week / hour-of-day extraction
------------------------------------
Postgres' ``EXTRACT`` works on the underlying timestamp. Times are stored
as UTC; the operator-relevant view is *local clock at the location*. We
push the conversion into SQL via ``timezone()`` so we don't need to
loop in Python:

    EXTRACT(dow FROM (s.scheduled_start AT TIME ZONE l.timezone))

Falls back to UTC when the location's timezone is missing (shouldn't
happen — ``locations.timezone`` is NOT NULL — but we don't crash on
historic data anyway).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import (
    String,
    and_,
    case,
    cast,
    func,
    literal,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.domain.enums import ShiftStatus, TaskStatus, UserRole
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import (
    Location,
    Shift,
    TaskInstance,
    User,
)


@dataclass(frozen=True, slots=True)
class KpiBlock:
    shifts_closed: int
    shifts_clean: int
    shifts_with_violations: int
    average_score: Decimal | None
    cleanliness_rate: Decimal | None  # shifts_clean / shifts_closed in [0, 1]


@dataclass(frozen=True, slots=True)
class HeatmapCell:
    """0-indexed: ``day_of_week=0`` is Sunday (Postgres ``EXTRACT(dow)``)."""

    day_of_week: int
    hour_of_day: int
    shift_count: int
    average_score: Decimal | None


@dataclass(frozen=True, slots=True)
class ViolatorRow:
    user_id: uuid.UUID
    full_name: str
    shifts_total: int
    shifts_with_violations: int
    average_score: Decimal | None


@dataclass(frozen=True, slots=True)
class LocationRow:
    location_id: uuid.UUID
    location_name: str
    shifts_total: int
    shifts_with_violations: int
    average_score: Decimal | None


@dataclass(frozen=True, slots=True)
class OverviewDTO:
    range_from: datetime
    range_to: datetime
    kpis: KpiBlock
    heatmap: list[HeatmapCell]
    top_violators: list[ViolatorRow]
    locations: list[LocationRow]


# Defaults chosen to mirror the UI: a four-week pilot window. The owner
# can override with ?days=7 / ?days=90 — anything beyond 365 is a
# performance smell (and the heatmap noise floor swamps the signal).
DEFAULT_DAYS = 30
MAX_DAYS = 365


class AnalyticsOverviewUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        user: CurrentUser,
        days: int,
        location_id: uuid.UUID | None = None,
    ) -> Result[OverviewDTO, DomainError]:
        if user.role not in (UserRole.ADMIN, UserRole.OWNER):
            return Failure(DomainError("forbidden"))

        days = max(1, min(days, MAX_DAYS))
        now = datetime.now(tz=UTC)
        range_from = now - timedelta(days=days)
        range_to = now

        kpis = await self._kpis(range_from, range_to, location_id)
        heatmap = await self._heatmap(range_from, range_to, location_id)
        violators = await self._top_violators(range_from, range_to, location_id)
        locations = await self._locations(range_from, range_to)

        return Success(
            OverviewDTO(
                range_from=range_from,
                range_to=range_to,
                kpis=kpis,
                heatmap=heatmap,
                top_violators=violators,
                locations=locations,
            )
        )

    # The "violation" predicate: a closed shift counts as having a
    # violation if any task ended up SKIPPED (= required-but-missed at
    # close time) or WAIVER_REJECTED. Critical tasks can't reach close
    # without being DONE/WAIVED (hard block), so this is the right
    # signal for the dashboard.
    @staticmethod
    def _violation_filter():  # type: ignore[no-untyped-def]
        return TaskInstance.status.in_(
            [TaskStatus.SKIPPED, TaskStatus.WAIVER_REJECTED]
        )

    def _closed_shift_filter(
        self,
        range_from: datetime,
        range_to: datetime,
        location_id: uuid.UUID | None,
    ):  # type: ignore[no-untyped-def]
        clauses = [
            Shift.status.in_(
                [
                    ShiftStatus.CLOSED_CLEAN,
                    ShiftStatus.CLOSED_WITH_VIOLATIONS,
                ]
            ),
            Shift.actual_end.isnot(None),
            Shift.actual_end >= range_from,
            Shift.actual_end <= range_to,
        ]
        if location_id is not None:
            clauses.append(Shift.location_id == location_id)
        return and_(*clauses)

    async def _kpis(
        self,
        range_from: datetime,
        range_to: datetime,
        location_id: uuid.UUID | None,
    ) -> KpiBlock:
        is_clean = case(
            (Shift.status == ShiftStatus.CLOSED_CLEAN, 1),
            else_=0,
        )
        is_violations = case(
            (Shift.status == ShiftStatus.CLOSED_WITH_VIOLATIONS, 1),
            else_=0,
        )
        stmt = select(
            func.count(Shift.id).label("total"),
            func.coalesce(func.sum(is_clean), 0).label("clean"),
            func.coalesce(func.sum(is_violations), 0).label("with_violations"),
            func.avg(Shift.score).label("avg_score"),
        ).where(self._closed_shift_filter(range_from, range_to, location_id))

        row = (await self._session.execute(stmt)).one()
        total = int(row.total or 0)
        clean = int(row.clean or 0)
        with_violations = int(row.with_violations or 0)
        avg_score: Decimal | None = (
            Decimal(row.avg_score).quantize(Decimal("0.01")) if row.avg_score is not None else None
        )
        cleanliness: Decimal | None = (
            (Decimal(clean) / Decimal(total)).quantize(Decimal("0.0001"))
            if total > 0
            else None
        )
        return KpiBlock(
            shifts_closed=total,
            shifts_clean=clean,
            shifts_with_violations=with_violations,
            average_score=avg_score,
            cleanliness_rate=cleanliness,
        )

    async def _heatmap(
        self,
        range_from: datetime,
        range_to: datetime,
        location_id: uuid.UUID | None,
    ) -> list[HeatmapCell]:
        # Convert to local time *at the location* before extracting bins.
        local_start = func.timezone(
            func.coalesce(Location.timezone, literal("UTC")),
            Shift.scheduled_start,
        )
        dow = cast(func.extract("dow", local_start), String)
        hod = cast(func.extract("hour", local_start), String)

        stmt = (
            select(
                cast(dow, String).label("dow"),
                cast(hod, String).label("hod"),
                func.count(Shift.id).label("n"),
                func.avg(Shift.score).label("avg_score"),
            )
            .select_from(Shift)
            .join(Location, Location.id == Shift.location_id)
            .where(self._closed_shift_filter(range_from, range_to, location_id))
            .group_by("dow", "hod")
        )

        rows = (await self._session.execute(stmt)).all()
        cells: list[HeatmapCell] = []
        for row in rows:
            try:
                day_idx = int(float(row.dow))
                hour_idx = int(float(row.hod))
            except (TypeError, ValueError):
                continue
            avg = (
                Decimal(row.avg_score).quantize(Decimal("0.01"))
                if row.avg_score is not None
                else None
            )
            cells.append(
                HeatmapCell(
                    day_of_week=day_idx,
                    hour_of_day=hour_idx,
                    shift_count=int(row.n or 0),
                    average_score=avg,
                )
            )
        return cells

    async def _top_violators(
        self,
        range_from: datetime,
        range_to: datetime,
        location_id: uuid.UUID | None,
        limit: int = 3,
    ) -> list[ViolatorRow]:
        # Sub-query: per shift, did *any* task land in a violation status?
        # We materialise this as a flag column so the outer aggregate
        # produces shifts_with_violations directly.
        violation_subq = (
            select(TaskInstance.shift_id)
            .where(self._violation_filter())
            .distinct()
            .subquery()
        )

        violation_flag = case(
            (violation_subq.c.shift_id.isnot(None), 1),
            else_=0,
        )

        stmt = (
            select(
                User.id.label("user_id"),
                User.full_name.label("full_name"),
                func.count(Shift.id).label("shifts_total"),
                func.coalesce(func.sum(violation_flag), 0).label("violations"),
                func.avg(Shift.score).label("avg_score"),
            )
            .select_from(Shift)
            .join(User, User.id == Shift.operator_user_id)
            .join(
                violation_subq,
                violation_subq.c.shift_id == Shift.id,
                isouter=True,
            )
            .where(self._closed_shift_filter(range_from, range_to, location_id))
            .group_by(User.id, User.full_name)
            # Owner cares about both rate and absolute count. We sort by
            # absolute violations DESC and ties by lowest avg score —
            # this surfaces both "many small slips" and "consistently bad".
            .order_by(
                func.coalesce(func.sum(violation_flag), 0).desc(),
                func.avg(Shift.score).asc().nullslast(),
            )
            .limit(limit)
        )

        rows = (await self._session.execute(stmt)).all()
        return [
            ViolatorRow(
                user_id=row.user_id,
                full_name=row.full_name,
                shifts_total=int(row.shifts_total or 0),
                shifts_with_violations=int(row.violations or 0),
                average_score=(
                    Decimal(row.avg_score).quantize(Decimal("0.01"))
                    if row.avg_score is not None
                    else None
                ),
            )
            for row in rows
        ]

    async def _locations(
        self,
        range_from: datetime,
        range_to: datetime,
    ) -> list[LocationRow]:
        # Same violation flag idea as in _top_violators, but grouped by
        # location instead of operator. We never filter by location here —
        # the locations breakdown is the comparison view.
        violation_subq = (
            select(TaskInstance.shift_id)
            .where(self._violation_filter())
            .distinct()
            .subquery()
        )
        violation_flag = case(
            (violation_subq.c.shift_id.isnot(None), 1),
            else_=0,
        )

        stmt = (
            select(
                Location.id.label("location_id"),
                Location.name.label("location_name"),
                func.count(Shift.id).label("shifts_total"),
                func.coalesce(func.sum(violation_flag), 0).label("violations"),
                func.avg(Shift.score).label("avg_score"),
            )
            .select_from(Shift)
            .join(Location, Location.id == Shift.location_id)
            .join(
                violation_subq,
                violation_subq.c.shift_id == Shift.id,
                isouter=True,
            )
            .where(self._closed_shift_filter(range_from, range_to, None))
            .group_by(Location.id, Location.name)
            .order_by(Location.name.asc())
        )

        rows = (await self._session.execute(stmt)).all()
        return [
            LocationRow(
                location_id=row.location_id,
                location_name=row.location_name,
                shifts_total=int(row.shifts_total or 0),
                shifts_with_violations=int(row.violations or 0),
                average_score=(
                    Decimal(row.avg_score).quantize(Decimal("0.01"))
                    if row.avg_score is not None
                    else None
                ),
            )
            for row in rows
        ]


__all__ = [
    "DEFAULT_DAYS",
    "MAX_DAYS",
    "AnalyticsOverviewUseCase",
    "HeatmapCell",
    "KpiBlock",
    "LocationRow",
    "OverviewDTO",
    "ViolatorRow",
]
