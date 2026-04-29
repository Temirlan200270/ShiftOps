"""Active shifts snapshot for the admin live monitor.

Why a separate use case from ``ListMyShiftUseCase``
---------------------------------------------------
The operator endpoint returns one shift; the monitor needs an
organisation-wide list with progress counts so the admin can see all
ongoing work on a single screen. Joining the bulk progress across
shifts in one query (vs. N round-trips in Python) is the difference
between a snappy first paint and a 2-second blank screen on Supabase
free-tier latency.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.domain.enums import ShiftStatus, TaskStatus, UserRole
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Location, Shift, TaskInstance, Template, User


@dataclass(frozen=True, slots=True)
class ActiveShiftDTO:
    shift_id: uuid.UUID
    location_id: uuid.UUID
    location_name: str
    template_name: str
    operator_id: uuid.UUID
    operator_name: str
    scheduled_start: datetime
    scheduled_end: datetime
    actual_start: datetime | None
    progress_total: int
    progress_done: int
    progress_critical_pending: int


class ListActiveShiftsUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, *, user: CurrentUser) -> Result[list[ActiveShiftDTO], DomainError]:
        if user.role not in (UserRole.ADMIN, UserRole.OWNER):
            return Failure(DomainError("forbidden"))

        # Active shifts only. RLS already scopes to the org.
        shifts_stmt = (
            select(Shift, Location, Template, User)
            .select_from(Shift)
            .join(Location, Location.id == Shift.location_id)
            .join(Template, Template.id == Shift.template_id)
            .join(User, User.id == Shift.operator_user_id)
            .where(Shift.status == ShiftStatus.ACTIVE)
            .order_by(Shift.actual_start.asc().nullslast(), Shift.scheduled_start.asc())
        )
        rows = (await self._session.execute(shifts_stmt)).all()
        if not rows:
            return Success([])

        shift_ids = [row[0].id for row in rows]
        progress_by_shift = await self._progress(shift_ids)

        items: list[ActiveShiftDTO] = []
        for shift, location, template, operator in rows:
            counts = progress_by_shift.get(
                shift.id, _ProgressCounts(total=0, done=0, critical_pending=0)
            )
            items.append(
                ActiveShiftDTO(
                    shift_id=shift.id,
                    location_id=location.id,
                    location_name=location.name,
                    template_name=template.name,
                    operator_id=operator.id,
                    operator_name=operator.full_name,
                    scheduled_start=shift.scheduled_start,
                    scheduled_end=shift.scheduled_end,
                    actual_start=shift.actual_start,
                    progress_total=counts.total,
                    progress_done=counts.done,
                    progress_critical_pending=counts.critical_pending,
                )
            )
        return Success(items)

    async def _progress(self, shift_ids: list[uuid.UUID]) -> dict[uuid.UUID, _ProgressCounts]:
        if not shift_ids:
            return {}
        from shiftops_api.infra.db.models import TemplateTask

        # Single round-trip: total tasks, completed (done OR waived), and
        # critical-pending so the UI can highlight the "blocked from
        # closure" shifts in the list.
        is_done = case(
            (TaskInstance.status.in_([TaskStatus.DONE, TaskStatus.WAIVED]), 1),
            else_=0,
        )
        is_critical_pending = case(
            (
                (TemplateTask.criticality == "critical")
                & (TaskInstance.status == TaskStatus.PENDING),
                1,
            ),
            else_=0,
        )
        stmt = (
            select(
                TaskInstance.shift_id,
                func.count(TaskInstance.id).label("total"),
                func.coalesce(func.sum(is_done), 0).label("done"),
                func.coalesce(func.sum(is_critical_pending), 0).label("critical_pending"),
            )
            .join(TemplateTask, TemplateTask.id == TaskInstance.template_task_id)
            .where(TaskInstance.shift_id.in_(shift_ids))
            .group_by(TaskInstance.shift_id)
        )
        result: dict[uuid.UUID, _ProgressCounts] = {}
        for shift_id, total, done, critical_pending in (await self._session.execute(stmt)).all():
            result[shift_id] = _ProgressCounts(
                total=int(total or 0),
                done=int(done or 0),
                critical_pending=int(critical_pending or 0),
            )
        return result


@dataclass(frozen=True, slots=True)
class _ProgressCounts:
    total: int
    done: int
    critical_pending: int


__all__ = ["ActiveShiftDTO", "ListActiveShiftsUseCase"]
