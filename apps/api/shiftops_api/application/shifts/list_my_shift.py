"""Use-case: return the operator's current (active or scheduled) shift + tasks.

Selection priority when the user has multiple shifts:
- If 2+ active shifts → show the newest (highest scheduled_start); the oldest
  is surfaced as ``unclosed_shift`` so the frontend can show a switch banner.
- If 1 active shift → show it.
- If 0 active → show nearest future scheduled (scheduled_end >= now).
- Otherwise → no_shift.

The optional ``shift_id`` parameter bypasses auto-selection and loads a
specific shift owned by the user (used by GET /shifts/{id}).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
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
class UnclosedShiftInfo:
    """Minimal info about an older active shift shown in the switch banner."""

    id: uuid.UUID
    template_name: str
    progress_done: int
    progress_total: int


@dataclass(frozen=True, slots=True)
class CurrentShiftDTO:
    shift: ShiftSummaryDTO
    tasks: list[TaskCardDTO]
    unclosed_shift: UnclosedShiftInfo | None = None


class ListMyShiftUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        user: CurrentUser,
        shift_id: uuid.UUID | None = None,
    ) -> Result[CurrentShiftDTO, DomainError]:
        if shift_id is not None:
            return await self._execute_by_id(user, shift_id)
        return await self._execute_current(user)

    # ── Main auto-selection path ──────────────────────────────────────────────

    async def _execute_current(
        self,
        user: CurrentUser,
    ) -> Result[CurrentShiftDTO, DomainError]:
        now = datetime.now(tz=UTC)
        rows = (
            await self._session.execute(
                select(Shift, Template, User)
                .join(Template, Template.id == Shift.template_id)
                .join(User, User.id == Shift.operator_user_id)
                .where(Shift.operator_user_id == user.id)
                .where(Shift.status.in_([ShiftStatus.ACTIVE, ShiftStatus.SCHEDULED]))
                .order_by(Shift.scheduled_start.asc())
            )
        ).all()

        if not rows:
            return Failure(DomainError("no_shift"))

        active = [(s, t, o) for s, t, o in rows if s.status == ShiftStatus.ACTIVE]
        scheduled = [(s, t, o) for s, t, o in rows if s.status == ShiftStatus.SCHEDULED]

        unclosed_shift: UnclosedShiftInfo | None = None

        if len(active) >= 2:
            # Newest active is the current working shift; oldest gets the banner.
            chosen = active[-1]
            unclosed_shift = await self._make_unclosed_info(active[0][0])
        elif len(active) == 1:
            chosen = active[0]
        else:
            future = [(s, t, o) for s, t, o in scheduled if s.scheduled_end >= now]
            if not future:
                return Failure(DomainError("no_shift"))
            chosen = future[0]

        shift, template, operator = chosen
        tasks, progress_done = await self._load_tasks(shift.id)
        return Success(
            CurrentShiftDTO(
                shift=self._to_dto(shift, template, operator, progress_done, len(tasks)),
                tasks=tasks,
                unclosed_shift=unclosed_shift,
            )
        )

    # ── Explicit shift-by-id path (GET /shifts/{id}) ─────────────────────────

    async def _execute_by_id(
        self,
        user: CurrentUser,
        shift_id: uuid.UUID,
    ) -> Result[CurrentShiftDTO, DomainError]:
        row = (
            await self._session.execute(
                select(Shift, Template, User)
                .join(Template, Template.id == Shift.template_id)
                .join(User, User.id == Shift.operator_user_id)
                .where(Shift.id == shift_id)
                .where(Shift.operator_user_id == user.id)
                .where(Shift.status.in_([ShiftStatus.ACTIVE, ShiftStatus.SCHEDULED]))
            )
        ).first()
        if row is None:
            return Failure(DomainError("shift_not_found"))

        shift, template, operator = row

        # Any OTHER active shift becomes the unclosed banner on this view too,
        # so the user can always switch back.
        other = (
            await self._session.execute(
                select(Shift)
                .where(Shift.operator_user_id == user.id)
                .where(Shift.status == ShiftStatus.ACTIVE)
                .where(Shift.id != shift_id)
                .order_by(Shift.scheduled_start.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        unclosed_shift = await self._make_unclosed_info(other) if other else None

        tasks, progress_done = await self._load_tasks(shift.id)
        return Success(
            CurrentShiftDTO(
                shift=self._to_dto(shift, template, operator, progress_done, len(tasks)),
                tasks=tasks,
                unclosed_shift=unclosed_shift,
            )
        )

    # ── Shared helpers ────────────────────────────────────────────────────────

    async def _make_unclosed_info(self, shift: Shift) -> UnclosedShiftInfo:
        template = await self._session.get(Template, shift.template_id)
        counts = (
            await self._session.execute(
                select(
                    func.count(TaskInstance.id).label("total"),
                    func.count(TaskInstance.id)
                    .filter(TaskInstance.status.in_(["done", "waived"]))
                    .label("done"),
                ).where(TaskInstance.shift_id == shift.id)
            )
        ).one()
        return UnclosedShiftInfo(
            id=shift.id,
            template_name=template.name if template else "—",
            progress_done=int(counts.done or 0),
            progress_total=int(counts.total or 0),
        )

    async def _load_tasks(
        self, shift_id: uuid.UUID
    ) -> tuple[list[TaskCardDTO], int]:
        task_rows = (
            await self._session.execute(
                select(TaskInstance, TemplateTask)
                .join(TemplateTask, TemplateTask.id == TaskInstance.template_task_id)
                .where(TaskInstance.shift_id == shift_id)
                .where(TaskInstance.status != TaskStatus.OBSOLETE.value)
                .order_by(TemplateTask.order_index.asc())
            )
        ).all()

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
        return cards, progress_done

    @staticmethod
    def _to_dto(
        shift: Shift,
        template: Template,
        operator: User,
        progress_done: int,
        progress_total: int,
    ) -> ShiftSummaryDTO:
        return ShiftSummaryDTO(
            id=shift.id,
            template_name=template.name,
            status=shift.status,
            score=float(shift.score) if shift.score is not None else None,
            progress_done=progress_done,
            progress_total=progress_total,
            scheduled_start=shift.scheduled_start.isoformat(),
            scheduled_end=shift.scheduled_end.isoformat(),
            actual_start=shift.actual_start.isoformat() if shift.actual_start else None,
            actual_end=shift.actual_end.isoformat() if shift.actual_end else None,
            operator_full_name=operator.full_name,
            slot_index=int(shift.slot_index),
            station_label=shift.station_label,
        )
