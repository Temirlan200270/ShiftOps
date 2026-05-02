"""Use-case: paginate the closed-shift history for the current operator.

Why this exists
---------------
Operators want a "what did I do last week" view. Owners and admins eventually
want this for *any* operator, but until we have the analytics dashboard
(V1.5) the operator-only view is enough to give pilot users a sense of
progress over time.

Pagination strategy: keyset on ``scheduled_start DESC``. Offset pagination
on a list that grows by one row per shift would be safe in practice, but
keyset is just as simple here and won't degrade if a manager has 5k shifts
under one account.

We never return an "active" or "scheduled" shift here — those live on
``GET /v1/shifts/me``. Mixing them would let the same row appear in two
endpoints, which downstream caches treat as inconsistency.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.domain.enums import ShiftStatus, TaskStatus, is_line_staff
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.domain.score import (
    ShiftScoreInputs,
    compute_score,
)
from shiftops_api.infra.db.models import (
    Attachment,
    Shift,
    TaskInstance,
    Template,
    TemplateTask,
)

# Hard cap on page size — the screen is a phone list, more rows than this
# = scroll fatigue + larger payloads. UI never asks for more.
MAX_PAGE_SIZE = 50
DEFAULT_PAGE_SIZE = 20


@dataclass(frozen=True, slots=True)
class HistoryRowDTO:
    id: uuid.UUID
    template_name: str
    status: str
    score: Decimal | None
    formula_version: int
    completion: Decimal | None
    critical_compliance: Decimal | None
    timeliness: Decimal | None
    photo_quality: Decimal | None
    scheduled_start: datetime
    scheduled_end: datetime
    actual_start: datetime | None
    actual_end: datetime | None
    tasks_total: int
    tasks_done: int
    handover_summary: str | None
    slot_index: int
    station_label: str | None
    delay_reason: str | None


@dataclass(frozen=True, slots=True)
class HistoryPageDTO:
    items: list[HistoryRowDTO]
    next_cursor: str | None  # ISO-8601 timestamp of the last row's scheduled_start


class ListHistoryUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        user: CurrentUser,
        cursor: datetime | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        target_user_id: uuid.UUID | None = None,
        location_id: uuid.UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        slot_index: int | None = None,
        station_label: str | None = None,
        station_label_empty: bool = False,
    ) -> Result[HistoryPageDTO, DomainError]:
        limit = min(max(limit, 1), MAX_PAGE_SIZE)

        # Authorization: an operator can only see their own history. Admins
        # / owners may pass an explicit ``target_user_id``; if they don't,
        # they see their own. We deliberately don't 403 a manager looking
        # at their own dashboard.
        if is_line_staff(user.role) and target_user_id and target_user_id != user.id:
            return Failure(DomainError("forbidden"))
        operator_id = target_user_id or user.id

        # Reject windows that are obviously a typo (to before from). We
        # don't try to fix it — the caller almost certainly has a bug.
        if date_from is not None and date_to is not None and date_to < date_from:
            return Failure(DomainError("invalid_range"))

        stmt = (
            select(Shift, Template)
            .join(Template, Template.id == Shift.template_id)
            .where(Shift.operator_user_id == operator_id)
            .where(
                Shift.status.in_(
                    [
                        ShiftStatus.CLOSED_CLEAN,
                        ShiftStatus.CLOSED_WITH_VIOLATIONS,
                        ShiftStatus.ABORTED,
                    ]
                )
            )
            .order_by(Shift.scheduled_start.desc())
            .limit(limit + 1)  # +1 lets us detect "is there a next page?"
        )
        if cursor is not None:
            stmt = stmt.where(Shift.scheduled_start < cursor)
        if location_id is not None:
            stmt = stmt.where(Shift.location_id == location_id)
        if date_from is not None:
            stmt = stmt.where(Shift.scheduled_start >= date_from)
        if date_to is not None:
            stmt = stmt.where(Shift.scheduled_start <= date_to)
        if slot_index is not None:
            stmt = stmt.where(Shift.slot_index == slot_index)
        if station_label_empty:
            stmt = stmt.where(Shift.station_label.is_(None))
        elif station_label is not None:
            stmt = stmt.where(Shift.station_label == station_label)

        rows = (await self._session.execute(stmt)).all()
        has_more = len(rows) > limit
        rows = rows[:limit]

        # Bulk-load task counts and breakdown ingredients in two queries
        # rather than N. With 50 shifts and 20 tasks each, the naive
        # approach is 100 round-trips on Supabase pooler latency = ~3 s.
        shift_ids = [s.id for s, _ in rows]
        tallies = await self._shift_tallies(shift_ids)

        items: list[HistoryRowDTO] = []
        for shift, template in rows:
            tally = tallies.get(shift.id, _TaskTally())
            photo_total, photo_unique = tally.photo_total, tally.photo_unique

            # Recompute the breakdown using the formula version stored on
            # the row — historical scores never silently shift.
            breakdown = None
            if shift.actual_end is not None and tally.total > 0:
                result = compute_score(
                    ShiftScoreInputs(
                        total_tasks=tally.total,
                        done_or_waived=tally.done_or_waived,
                        critical_total=tally.critical_total,
                        critical_done_or_waived=tally.critical_done_or_waived,
                        photo_total=photo_total,
                        photo_unique=photo_unique,
                        scheduled_end=shift.scheduled_end,
                        actual_end=shift.actual_end,
                    ),
                    version=shift.score_formula_version or 1,
                )
                breakdown = result.breakdown

            items.append(
                HistoryRowDTO(
                    id=shift.id,
                    template_name=template.name,
                    status=shift.status,
                    score=shift.score,
                    formula_version=shift.score_formula_version or 1,
                    completion=breakdown.completion if breakdown else None,
                    critical_compliance=(breakdown.critical_compliance if breakdown else None),
                    timeliness=breakdown.timeliness if breakdown else None,
                    photo_quality=breakdown.photo_quality if breakdown else None,
                    scheduled_start=shift.scheduled_start,
                    scheduled_end=shift.scheduled_end,
                    actual_start=shift.actual_start,
                    actual_end=shift.actual_end,
                    tasks_total=tally.total,
                    tasks_done=tally.done_or_waived,
                    handover_summary=shift.handover_summary,
                    slot_index=int(shift.slot_index),
                    station_label=shift.station_label,
                    delay_reason=shift.delay_reason,
                )
            )

        next_cursor = (
            items[-1].scheduled_start.astimezone(UTC).isoformat() if (has_more and items) else None
        )
        return Success(HistoryPageDTO(items=items, next_cursor=next_cursor))

    async def _shift_tallies(self, shift_ids: list[uuid.UUID]) -> dict[uuid.UUID, _TaskTally]:
        if not shift_ids:
            return {}
        done_states = (TaskStatus.DONE.value, TaskStatus.WAIVED.value)
        task_sq = (
            select(
                TaskInstance.shift_id.label("shift_id"),
                func.count().label("total"),
                func.sum(
                    case((TaskInstance.status.in_(done_states), 1), else_=0),
                ).label("done_or_waived"),
                func.sum(case((TemplateTask.criticality == "critical", 1), else_=0)).label(
                    "critical_total"
                ),
                func.sum(
                    case(
                        (
                            (TemplateTask.criticality == "critical")
                            & TaskInstance.status.in_(done_states),
                            1,
                        ),
                        else_=0,
                    ),
                ).label("critical_done_or_waived"),
            )
            .join(TemplateTask, TemplateTask.id == TaskInstance.template_task_id)
            .where(TaskInstance.shift_id.in_(shift_ids))
            .group_by(TaskInstance.shift_id)
        ).subquery()
        photo_sq = (
            select(
                TaskInstance.shift_id.label("shift_id"),
                func.count(Attachment.id).label("photo_total"),
                func.count().filter(~Attachment.suspicious).label("photo_unique"),
            )
            .select_from(Attachment)
            .join(TaskInstance, TaskInstance.id == Attachment.task_instance_id)
            .where(TaskInstance.shift_id.in_(shift_ids))
            .group_by(TaskInstance.shift_id)
        ).subquery()

        stmt = select(
            func.coalesce(task_sq.c.shift_id, photo_sq.c.shift_id).label("shift_id"),
            task_sq.c.total,
            task_sq.c.done_or_waived,
            task_sq.c.critical_total,
            task_sq.c.critical_done_or_waived,
            photo_sq.c.photo_total,
            photo_sq.c.photo_unique,
        ).select_from(task_sq.join(photo_sq, task_sq.c.shift_id == photo_sq.c.shift_id, full=True))

        out: dict[uuid.UUID, _TaskTally] = {sid: _TaskTally() for sid in shift_ids}
        for (
            sid,
            total,
            done_ow,
            crit_tot,
            crit_done,
            ptot,
            puniq,
        ) in (await self._session.execute(stmt)).all():
            if sid is None:
                continue
            row = out[sid]
            row.total = int(total or 0)
            row.done_or_waived = int(done_ow or 0)
            row.critical_total = int(crit_tot or 0)
            row.critical_done_or_waived = int(crit_done or 0)
            row.photo_total = int(ptot or 0)
            row.photo_unique = int(puniq or 0)
        return out


@dataclass
class _TaskTally:
    total: int = 0
    done_or_waived: int = 0
    critical_total: int = 0
    critical_done_or_waived: int = 0
    photo_total: int = 0
    photo_unique: int = 0
