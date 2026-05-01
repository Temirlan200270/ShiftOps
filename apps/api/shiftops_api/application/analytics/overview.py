"""S9 — Owner / admin overview dashboard (v2).

The screen sources from a single ``/v1/analytics/overview`` payload: KPI,
heatmap, top violators, locations, plus four new breakdowns (templates,
criticality, anti-fake, SLA late-start) and a role split (operator vs
bartender). When ``compare`` is enabled we also return the same payload
shape for the previous window of equal length under ``previous`` so the
UI can render dual columns and a delta.

Day-of-week / hour-of-day extraction
------------------------------------
Postgres ``EXTRACT`` runs on the underlying timestamp. Times are stored in
UTC; the operator-relevant view is *local clock at the location*. We push
the conversion into SQL via ``timezone()`` so we don't loop in Python:

    EXTRACT(dow FROM (s.scheduled_start AT TIME ZONE l.timezone))

Falls back to UTC when the location's timezone is missing (shouldn't happen
in production data — ``locations.timezone`` is NOT NULL — but historic data
should not crash the dashboard).

Density flags
-------------
We tag each block with ``"empty" | "low" | "ok"`` so the UI can show a
"few data points" hint instead of pretending a 2-shift sample size is
trustworthy. Thresholds are conservative on purpose: a noisy heatmap with
< 20 closed shifts is statistically meaningless.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

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
from shiftops_api.config import get_settings
from shiftops_api.domain.enums import ShiftStatus, TaskStatus, UserRole
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import (
    Attachment,
    Location,
    Shift,
    TaskInstance,
    Template,
    TemplateTask,
    User,
)

# --- Public constants ------------------------------------------------------

DEFAULT_DAYS = 30
MAX_DAYS = 365
DEFAULT_VIOLATORS_LIMIT = 10
MIN_VIOLATORS_LIMIT = 1
MAX_VIOLATORS_LIMIT = 50

# Density thresholds: below these, the block is flagged "low" so the UI
# can warn that conclusions are unstable.
_KPI_LOW_THRESHOLD = 5
_HEATMAP_LOW_THRESHOLD = 20
_VIOLATOR_MIN_SHIFTS = 3
_VIOLATORS_LOW_ROWS = 3
_TEMPLATES_LOW_ROWS = 2

DensityFlag = Literal["empty", "low", "ok"]


# --- DTOs -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KpiBlock:
    shifts_closed: int
    shifts_clean: int
    shifts_with_violations: int
    average_score: Decimal | None
    cleanliness_rate: Decimal | None  # in [0, 1]


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
    role: str
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
class TemplateRow:
    template_id: uuid.UUID
    template_name: str
    shifts_total: int
    shifts_with_violations: int
    average_score: Decimal | None


@dataclass(frozen=True, slots=True)
class CriticalityRow:
    criticality: str  # "critical" | "required" | "optional"
    tasks_total: int
    done: int
    skipped: int
    waiver_rejected: int
    suspicious_attachments: int


@dataclass(frozen=True, slots=True)
class AntifakeBlock:
    attachments_total: int
    suspicious_total: int
    suspicious_rate: Decimal | None  # in [0, 1]


@dataclass(frozen=True, slots=True)
class SlaBlock:
    threshold_min: int
    shifts_with_actual: int
    late_count: int
    late_rate: Decimal | None  # in [0, 1]
    avg_late_min: Decimal | None  # average lateness for *late* shifts


@dataclass(frozen=True, slots=True)
class RoleSplitBlock:
    operator: KpiBlock
    bartender: KpiBlock


@dataclass(frozen=True, slots=True)
class DensityBlock:
    kpis: DensityFlag
    heatmap: DensityFlag
    violators: DensityFlag
    templates: DensityFlag


@dataclass(frozen=True, slots=True)
class OverviewDTO:
    range_from: datetime
    range_to: datetime
    kpis: KpiBlock
    heatmap: list[HeatmapCell]
    top_violators: list[ViolatorRow]
    locations: list[LocationRow]
    templates: list[TemplateRow] = field(default_factory=list)
    criticality: list[CriticalityRow] = field(default_factory=list)
    antifake: AntifakeBlock | None = None
    sla_late_start: SlaBlock | None = None
    role_split: RoleSplitBlock | None = None
    density: DensityBlock | None = None
    previous: OverviewDTO | None = None


# --- Use case -------------------------------------------------------------


class AnalyticsOverviewUseCase:
    """Owner-side analytics aggregator.

    Tradeoff: we issue ~9 small SELECTs per call rather than one giant CTE
    because (a) the queries are independent, (b) the dashboard already
    survives a 90 ms total budget on Supabase pooler, and (c) keeping each
    block in its own method makes the densitiy flags self-documenting.
    """

    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        user: CurrentUser,
        range_from: datetime,
        range_to: datetime,
        location_id: uuid.UUID | None = None,
        violators_limit: int = DEFAULT_VIOLATORS_LIMIT,
        compare: bool = False,
    ) -> Result[OverviewDTO, DomainError]:
        if user.role not in (UserRole.ADMIN, UserRole.OWNER):
            return Failure(DomainError("forbidden"))

        if range_to <= range_from:
            return Failure(DomainError("invalid_range"))
        # Defensive cap: a 5-year query on a free pooler is not "give us
        # the all-time view", it is "kill the page". MAX_DAYS already
        # exists as the "do not even try" line.
        if (range_to - range_from) > timedelta(days=MAX_DAYS):
            return Failure(DomainError("range_too_large"))

        violators_limit = max(MIN_VIOLATORS_LIMIT, min(violators_limit, MAX_VIOLATORS_LIMIT))

        current = await self._build(
            range_from=range_from,
            range_to=range_to,
            location_id=location_id,
            violators_limit=violators_limit,
        )

        previous: OverviewDTO | None = None
        if compare:
            duration = range_to - range_from
            prev_to = range_from
            prev_from = prev_to - duration
            previous = await self._build(
                range_from=prev_from,
                range_to=prev_to,
                location_id=location_id,
                violators_limit=violators_limit,
            )

        return Success(
            OverviewDTO(
                range_from=current.range_from,
                range_to=current.range_to,
                kpis=current.kpis,
                heatmap=current.heatmap,
                top_violators=current.top_violators,
                locations=current.locations,
                templates=current.templates,
                criticality=current.criticality,
                antifake=current.antifake,
                sla_late_start=current.sla_late_start,
                role_split=current.role_split,
                density=current.density,
                previous=previous,
            )
        )

    async def _build(
        self,
        *,
        range_from: datetime,
        range_to: datetime,
        location_id: uuid.UUID | None,
        violators_limit: int,
    ) -> OverviewDTO:
        kpis = await self._kpis(range_from, range_to, location_id)
        heatmap = await self._heatmap(range_from, range_to, location_id)
        violators = await self._top_violators(
            range_from, range_to, location_id, limit=violators_limit
        )
        locations = await self._locations(range_from, range_to)
        templates = await self._templates(range_from, range_to, location_id)
        criticality = await self._criticality(range_from, range_to, location_id)
        antifake = await self._antifake(range_from, range_to, location_id)
        sla = await self._sla(range_from, range_to, location_id)
        role_split = await self._role_split(range_from, range_to, location_id)
        density = self._density(
            kpis=kpis, heatmap=heatmap, violators=violators, templates=templates
        )
        return OverviewDTO(
            range_from=range_from,
            range_to=range_to,
            kpis=kpis,
            heatmap=heatmap,
            top_violators=violators,
            locations=locations,
            templates=templates,
            criticality=criticality,
            antifake=antifake,
            sla_late_start=sla,
            role_split=role_split,
            density=density,
        )

    # --- Filter helpers ---------------------------------------------------

    @staticmethod
    def _violation_filter():  # type: ignore[no-untyped-def]
        return TaskInstance.status.in_([TaskStatus.SKIPPED, TaskStatus.WAIVER_REJECTED])

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
            Shift.operator_user_id.isnot(None),
        ]
        if location_id is not None:
            clauses.append(Shift.location_id == location_id)
        return and_(*clauses)

    # --- Queries ----------------------------------------------------------

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
        return _kpi_from_row(row)

    async def _heatmap(
        self,
        range_from: datetime,
        range_to: datetime,
        location_id: uuid.UUID | None,
    ) -> list[HeatmapCell]:
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
            cells.append(
                HeatmapCell(
                    day_of_week=day_idx,
                    hour_of_day=hour_idx,
                    shift_count=int(row.n or 0),
                    average_score=_quantize_score(row.avg_score),
                )
            )
        return cells

    async def _top_violators(
        self,
        range_from: datetime,
        range_to: datetime,
        location_id: uuid.UUID | None,
        *,
        limit: int,
    ) -> list[ViolatorRow]:
        violation_subq = (
            select(TaskInstance.shift_id).where(self._violation_filter()).distinct().subquery()
        )
        violation_flag = case(
            (violation_subq.c.shift_id.isnot(None), 1),
            else_=0,
        )

        stmt = (
            select(
                User.id.label("user_id"),
                User.full_name.label("full_name"),
                User.role.label("role"),
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
            .group_by(User.id, User.full_name, User.role)
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
                role=row.role or "",
                shifts_total=int(row.shifts_total or 0),
                shifts_with_violations=int(row.violations or 0),
                average_score=_quantize_score(row.avg_score),
            )
            for row in rows
        ]

    async def _locations(
        self,
        range_from: datetime,
        range_to: datetime,
    ) -> list[LocationRow]:
        violation_subq = (
            select(TaskInstance.shift_id).where(self._violation_filter()).distinct().subquery()
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
                average_score=_quantize_score(row.avg_score),
            )
            for row in rows
        ]

    async def _templates(
        self,
        range_from: datetime,
        range_to: datetime,
        location_id: uuid.UUID | None,
    ) -> list[TemplateRow]:
        violation_subq = (
            select(TaskInstance.shift_id).where(self._violation_filter()).distinct().subquery()
        )
        violation_flag = case(
            (violation_subq.c.shift_id.isnot(None), 1),
            else_=0,
        )

        stmt = (
            select(
                Template.id.label("template_id"),
                Template.name.label("template_name"),
                func.count(Shift.id).label("shifts_total"),
                func.coalesce(func.sum(violation_flag), 0).label("violations"),
                func.avg(Shift.score).label("avg_score"),
            )
            .select_from(Shift)
            .join(Template, Template.id == Shift.template_id)
            .join(
                violation_subq,
                violation_subq.c.shift_id == Shift.id,
                isouter=True,
            )
            .where(self._closed_shift_filter(range_from, range_to, location_id))
            .group_by(Template.id, Template.name)
            .order_by(Template.name.asc())
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            TemplateRow(
                template_id=row.template_id,
                template_name=row.template_name,
                shifts_total=int(row.shifts_total or 0),
                shifts_with_violations=int(row.violations or 0),
                average_score=_quantize_score(row.avg_score),
            )
            for row in rows
        ]

    async def _criticality(
        self,
        range_from: datetime,
        range_to: datetime,
        location_id: uuid.UUID | None,
    ) -> list[CriticalityRow]:
        # Build per-criticality buckets from task instances that belong to
        # closed shifts in the window. Suspicious attachments are counted on
        # the same task ids via a correlated subquery to keep this one
        # round-trip.
        suspicious_subq = (
            select(
                Attachment.task_instance_id.label("task_id"),
                func.count(Attachment.id).label("n"),
            )
            .where(Attachment.suspicious.is_(True))
            .group_by(Attachment.task_instance_id)
            .subquery()
        )

        is_done = case(
            (
                TaskInstance.status.in_([TaskStatus.DONE, TaskStatus.WAIVED]),
                1,
            ),
            else_=0,
        )
        is_skipped = case((TaskInstance.status == TaskStatus.SKIPPED, 1), else_=0)
        is_rejected = case((TaskInstance.status == TaskStatus.WAIVER_REJECTED, 1), else_=0)

        stmt = (
            select(
                TemplateTask.criticality.label("criticality"),
                func.count(TaskInstance.id).label("total"),
                func.coalesce(func.sum(is_done), 0).label("done"),
                func.coalesce(func.sum(is_skipped), 0).label("skipped"),
                func.coalesce(func.sum(is_rejected), 0).label("rejected"),
                func.coalesce(func.sum(suspicious_subq.c.n), 0).label("susp"),
            )
            .select_from(TaskInstance)
            .join(Shift, Shift.id == TaskInstance.shift_id)
            .join(TemplateTask, TemplateTask.id == TaskInstance.template_task_id)
            .join(
                suspicious_subq,
                suspicious_subq.c.task_id == TaskInstance.id,
                isouter=True,
            )
            .where(self._closed_shift_filter(range_from, range_to, location_id))
            .group_by(TemplateTask.criticality)
            .order_by(TemplateTask.criticality.asc())
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            CriticalityRow(
                criticality=row.criticality,
                tasks_total=int(row.total or 0),
                done=int(row.done or 0),
                skipped=int(row.skipped or 0),
                waiver_rejected=int(row.rejected or 0),
                suspicious_attachments=int(row.susp or 0),
            )
            for row in rows
        ]

    async def _antifake(
        self,
        range_from: datetime,
        range_to: datetime,
        location_id: uuid.UUID | None,
    ) -> AntifakeBlock:
        is_susp = case((Attachment.suspicious.is_(True), 1), else_=0)
        stmt = (
            select(
                func.count(Attachment.id).label("total"),
                func.coalesce(func.sum(is_susp), 0).label("susp"),
            )
            .select_from(Attachment)
            .join(TaskInstance, TaskInstance.id == Attachment.task_instance_id)
            .join(Shift, Shift.id == TaskInstance.shift_id)
            .where(self._closed_shift_filter(range_from, range_to, location_id))
        )
        row = (await self._session.execute(stmt)).one()
        total = int(row.total or 0)
        susp = int(row.susp or 0)
        rate: Decimal | None = (
            (Decimal(susp) / Decimal(total)).quantize(Decimal("0.0001")) if total > 0 else None
        )
        return AntifakeBlock(
            attachments_total=total,
            suspicious_total=susp,
            suspicious_rate=rate,
        )

    async def _sla(
        self,
        range_from: datetime,
        range_to: datetime,
        location_id: uuid.UUID | None,
    ) -> SlaBlock:
        threshold = max(0, int(get_settings().analytics_sla_late_start_min))

        # Compute lateness in minutes inside SQL: EXTRACT(epoch FROM diff) / 60.
        late_min_expr = func.extract("epoch", Shift.actual_start - Shift.scheduled_start) / 60
        is_late = case(
            (
                and_(
                    Shift.actual_start.isnot(None),
                    late_min_expr > threshold,
                ),
                1,
            ),
            else_=0,
        )
        late_minutes_for_late_only = case(
            (
                and_(
                    Shift.actual_start.isnot(None),
                    late_min_expr > threshold,
                ),
                late_min_expr,
            )
        )

        stmt = select(
            func.coalesce(
                func.sum(case((Shift.actual_start.isnot(None), 1), else_=0)),
                0,
            ).label("with_actual"),
            func.coalesce(func.sum(is_late), 0).label("late_count"),
            func.avg(late_minutes_for_late_only).label("avg_late"),
        ).where(self._closed_shift_filter(range_from, range_to, location_id))

        row = (await self._session.execute(stmt)).one()
        with_actual = int(row.with_actual or 0)
        late_count = int(row.late_count or 0)
        late_rate: Decimal | None = (
            (Decimal(late_count) / Decimal(with_actual)).quantize(Decimal("0.0001"))
            if with_actual > 0
            else None
        )
        avg_late: Decimal | None = (
            Decimal(row.avg_late).quantize(Decimal("0.1")) if row.avg_late is not None else None
        )
        return SlaBlock(
            threshold_min=threshold,
            shifts_with_actual=with_actual,
            late_count=late_count,
            late_rate=late_rate,
            avg_late_min=avg_late,
        )

    async def _role_split(
        self,
        range_from: datetime,
        range_to: datetime,
        location_id: uuid.UUID | None,
    ) -> RoleSplitBlock:
        is_clean = case((Shift.status == ShiftStatus.CLOSED_CLEAN, 1), else_=0)
        is_violations = case((Shift.status == ShiftStatus.CLOSED_WITH_VIOLATIONS, 1), else_=0)

        stmt = (
            select(
                User.role.label("role"),
                func.count(Shift.id).label("total"),
                func.coalesce(func.sum(is_clean), 0).label("clean"),
                func.coalesce(func.sum(is_violations), 0).label("with_violations"),
                func.avg(Shift.score).label("avg_score"),
            )
            .select_from(Shift)
            .join(User, User.id == Shift.operator_user_id)
            .where(self._closed_shift_filter(range_from, range_to, location_id))
            .group_by(User.role)
        )
        rows = (await self._session.execute(stmt)).all()
        by_role: dict[str, KpiBlock] = {}
        for row in rows:
            by_role[row.role or ""] = _kpi_from_row(row)
        empty = KpiBlock(
            shifts_closed=0,
            shifts_clean=0,
            shifts_with_violations=0,
            average_score=None,
            cleanliness_rate=None,
        )
        return RoleSplitBlock(
            operator=by_role.get(UserRole.OPERATOR.value, empty),
            bartender=by_role.get(UserRole.BARTENDER.value, empty),
        )

    # --- Density ----------------------------------------------------------

    @staticmethod
    def _density(
        *,
        kpis: KpiBlock,
        heatmap: list[HeatmapCell],
        violators: list[ViolatorRow],
        templates: list[TemplateRow],
    ) -> DensityBlock:
        kpi_d: DensityFlag = (
            "empty"
            if kpis.shifts_closed == 0
            else ("low" if kpis.shifts_closed < _KPI_LOW_THRESHOLD else "ok")
        )
        heat_d: DensityFlag = (
            "empty"
            if not heatmap
            else ("low" if kpis.shifts_closed < _HEATMAP_LOW_THRESHOLD else "ok")
        )
        eligible_violators = sum(1 for v in violators if v.shifts_total >= _VIOLATOR_MIN_SHIFTS)
        viol_d: DensityFlag = (
            "empty"
            if not violators
            else ("low" if eligible_violators < _VIOLATORS_LOW_ROWS else "ok")
        )
        tpl_d: DensityFlag = (
            "empty" if not templates else ("low" if len(templates) < _TEMPLATES_LOW_ROWS else "ok")
        )
        return DensityBlock(
            kpis=kpi_d,
            heatmap=heat_d,
            violators=viol_d,
            templates=tpl_d,
        )


# --- Helpers --------------------------------------------------------------


def _quantize_score(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value).quantize(Decimal("0.01"))


def _kpi_from_row(row: object) -> KpiBlock:  # type: ignore[no-untyped-def]
    total = int(getattr(row, "total", 0) or 0)
    clean = int(getattr(row, "clean", 0) or 0)
    with_violations = int(getattr(row, "with_violations", 0) or 0)
    avg_score = _quantize_score(getattr(row, "avg_score", None))
    cleanliness: Decimal | None = (
        (Decimal(clean) / Decimal(total)).quantize(Decimal("0.0001")) if total > 0 else None
    )
    return KpiBlock(
        shifts_closed=total,
        shifts_clean=clean,
        shifts_with_violations=with_violations,
        average_score=avg_score,
        cleanliness_rate=cleanliness,
    )


__all__ = [
    "DEFAULT_DAYS",
    "DEFAULT_VIOLATORS_LIMIT",
    "MAX_DAYS",
    "MAX_VIOLATORS_LIMIT",
    "MIN_VIOLATORS_LIMIT",
    "AnalyticsOverviewUseCase",
    "AntifakeBlock",
    "CriticalityRow",
    "DensityBlock",
    "HeatmapCell",
    "KpiBlock",
    "LocationRow",
    "OverviewDTO",
    "RoleSplitBlock",
    "SlaBlock",
    "TemplateRow",
    "ViolatorRow",
]
