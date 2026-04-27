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
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.domain.enums import ShiftStatus, TaskStatus, UserRole
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
    ) -> Result[HistoryPageDTO, DomainError]:
        limit = min(max(limit, 1), MAX_PAGE_SIZE)

        # Authorization: an operator can only see their own history. Admins
        # / owners may pass an explicit ``target_user_id``; if they don't,
        # they see their own. We deliberately don't 403 a manager looking
        # at their own dashboard.
        if user.role == UserRole.OPERATOR and target_user_id and target_user_id != user.id:
            return Failure(DomainError("forbidden"))
        operator_id = target_user_id or user.id

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

        rows = (await self._session.execute(stmt)).all()
        has_more = len(rows) > limit
        rows = rows[:limit]

        # Bulk-load task counts and breakdown ingredients in two queries
        # rather than N. With 50 shifts and 20 tasks each, the naive
        # approach is 100 round-trips on Supabase pooler latency = ~3 s.
        shift_ids = [s.id for s, _ in rows]
        task_counts = await self._tally_tasks(shift_ids)
        photo_counts = await self._tally_photos(shift_ids)

        items: list[HistoryRowDTO] = []
        for shift, template in rows:
            tally = task_counts.get(shift.id, _TaskTally())
            photo_total, photo_unique = photo_counts.get(shift.id, (0, 0))

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
                    critical_compliance=(
                        breakdown.critical_compliance if breakdown else None
                    ),
                    timeliness=breakdown.timeliness if breakdown else None,
                    photo_quality=breakdown.photo_quality if breakdown else None,
                    scheduled_start=shift.scheduled_start,
                    scheduled_end=shift.scheduled_end,
                    actual_start=shift.actual_start,
                    actual_end=shift.actual_end,
                    tasks_total=tally.total,
                    tasks_done=tally.done_or_waived,
                )
            )

        next_cursor = (
            items[-1].scheduled_start.astimezone(timezone.utc).isoformat()
            if (has_more and items)
            else None
        )
        return Success(HistoryPageDTO(items=items, next_cursor=next_cursor))

    async def _tally_tasks(
        self, shift_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, "_TaskTally"]:
        if not shift_ids:
            return {}
        # One round-trip; group counts by status & criticality so we can
        # reconstruct the tally without round-tripping per shift.
        stmt = (
            select(
                TaskInstance.shift_id,
                TaskInstance.status,
                TemplateTask.criticality,
                func.count().label("n"),
            )
            .join(TemplateTask, TemplateTask.id == TaskInstance.template_task_id)
            .where(TaskInstance.shift_id.in_(shift_ids))
            .group_by(TaskInstance.shift_id, TaskInstance.status, TemplateTask.criticality)
        )
        out: dict[uuid.UUID, _TaskTally] = {sid: _TaskTally() for sid in shift_ids}
        for shift_id, task_status, criticality, n in (
            await self._session.execute(stmt)
        ).all():
            tally = out[shift_id]
            tally.total += n
            done = TaskStatus(task_status) in (TaskStatus.DONE, TaskStatus.WAIVED)
            if done:
                tally.done_or_waived += n
            if criticality == "critical":
                tally.critical_total += n
                if done:
                    tally.critical_done_or_waived += n
        return out

    async def _tally_photos(
        self, shift_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[int, int]]:
        """Return ``(photo_total, photo_unique)`` per shift."""
        if not shift_ids:
            return {}
        stmt = (
            select(
                TaskInstance.shift_id,
                func.count().label("total"),
                func.count().filter(Attachment.suspicious.is_(False)).label("unique"),
            )
            .select_from(Attachment)
            .join(TaskInstance, TaskInstance.id == Attachment.task_instance_id)
            .where(TaskInstance.shift_id.in_(shift_ids))
            .group_by(TaskInstance.shift_id)
        )
        result: dict[uuid.UUID, tuple[int, int]] = {}
        for shift_id, total, unique in (await self._session.execute(stmt)).all():
            result[shift_id] = (int(total or 0), int(unique or 0))
        return result


@dataclass
class _TaskTally:
    total: int = 0
    done_or_waived: int = 0
    critical_total: int = 0
    critical_done_or_waived: int = 0
