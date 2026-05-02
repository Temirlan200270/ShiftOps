"""Use-case: return the operator's current (active or scheduled) shift + tasks.

If both an active and a scheduled shift exist, prefer the active one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.domain.enums import ShiftStatus, TaskStatus
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import (
    Attachment,
    Shift,
    TaskInstance,
    Template,
    TemplateTask,
    User,
)


@dataclass(frozen=True, slots=True)
class TaskCardDTO:
    id: uuid.UUID
    title: str
    description: str | None
    section: str | None
    criticality: str
    requires_photo: bool
    requires_comment: bool
    status: str
    comment: str | None
    has_attachment: bool
    completed_at: str | None


@dataclass(frozen=True, slots=True)
class ShiftSummaryDTO:
    id: uuid.UUID
    template_name: str
    status: str
    score: float | None
    progress_done: int
    progress_total: int
    scheduled_start: str
    scheduled_end: str
    actual_start: str | None
    actual_end: str | None
    operator_full_name: str
    slot_index: int
    station_label: str | None


@dataclass(frozen=True, slots=True)
class CurrentShiftDTO:
    shift: ShiftSummaryDTO
    tasks: list[TaskCardDTO]


class ListMyShiftUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        user: CurrentUser,
    ) -> Result[CurrentShiftDTO, DomainError]:
        now = datetime.now(tz=UTC)
        active_stmt = (
            select(Shift, Template, User)
            .join(Template, Template.id == Shift.template_id)
            .join(User, User.id == Shift.operator_user_id)
            .where(Shift.operator_user_id == user.id)
            .where(Shift.status.in_([ShiftStatus.ACTIVE, ShiftStatus.SCHEDULED]))
            .order_by(Shift.scheduled_start.asc())
        )
        rows = (await self._session.execute(active_stmt)).all()
        if not rows:
            return Failure(DomainError("no_shift"))

        # Prefer active over scheduled; otherwise the soonest scheduled in the
        # future.
        chosen: tuple[Shift, Template, User] | None = None
        for shift, tpl, op in rows:
            if shift.status == ShiftStatus.ACTIVE:
                chosen = (shift, tpl, op)
                break
        if chosen is None:
            future = [(s, t, o) for s, t, o in rows if s.scheduled_start >= now]
            chosen = future[0] if future else rows[0]

        shift, template, operator = chosen

        tasks_stmt = (
            select(TaskInstance, TemplateTask)
            .join(TemplateTask, TemplateTask.id == TaskInstance.template_task_id)
            .where(TaskInstance.shift_id == shift.id)
            .where(TaskInstance.status != TaskStatus.OBSOLETE.value)
            .order_by(TemplateTask.order_index.asc())
        )
        task_rows = (await self._session.execute(tasks_stmt)).all()

        attachments = {
            a.task_instance_id
            for a in (
                await self._session.execute(
                    select(Attachment).where(
                        Attachment.task_instance_id.in_([t.id for t, _ in task_rows])
                    )
                )
            ).scalars()
        }

        progress_done = 0
        cards: list[TaskCardDTO] = []
        for task, tt in task_rows:
            if TaskStatus(task.status) in (TaskStatus.DONE, TaskStatus.WAIVED):
                progress_done += 1
            cards.append(
                TaskCardDTO(
                    id=task.id,
                    title=tt.title,
                    description=tt.description,
                    section=tt.section,
                    criticality=tt.criticality,
                    requires_photo=tt.requires_photo,
                    requires_comment=tt.requires_comment,
                    status=task.status,
                    comment=task.comment,
                    has_attachment=task.id in attachments,
                    completed_at=task.completed_at.isoformat() if task.completed_at else None,
                )
            )

        return Success(
            CurrentShiftDTO(
                shift=ShiftSummaryDTO(
                    id=shift.id,
                    template_name=template.name,
                    status=shift.status,
                    score=float(shift.score) if shift.score is not None else None,
                    progress_done=progress_done,
                    progress_total=len(cards),
                    scheduled_start=shift.scheduled_start.isoformat(),
                    scheduled_end=shift.scheduled_end.isoformat(),
                    actual_start=shift.actual_start.isoformat() if shift.actual_start else None,
                    actual_end=shift.actual_end.isoformat() if shift.actual_end else None,
                    operator_full_name=operator.full_name,
                    slot_index=int(shift.slot_index),
                    station_label=shift.station_label,
                ),
                tasks=cards,
            )
        )
