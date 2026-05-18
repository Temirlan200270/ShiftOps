"""Batch-complete multiple tasks in a single DB transaction.

Tasks with ``requires_photo=True`` may be included — completing without a
photo is allowed (same behaviour as the single-task endpoint without a file
upload). The caller is responsible for warning the user before submitting.

Tasks with ``requires_comment=True`` are rejected — a comment requires
explicit user input and cannot be inferred automatically.

Constraints enforced here:
- All task IDs must belong to the current operator's active shift.
- ``requires_comment=True`` → rejected (use the single-task endpoint).
- Tasks must be in ``pending`` or ``waiver_rejected`` state.
- Max 50 IDs per call to bound query complexity.
"""

from __future__ import annotations

import asyncio
import uuid

# Strong references to fire-and-forget tasks (RUF006 / asyncio docs).
_bg_tasks: set[asyncio.Task[None]] = set()


def _fire(coro: asyncio.coroutines.CoroutineType) -> None:  # type: ignore[type-arg]
    task: asyncio.Task[None] = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.audit import write_audit
from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.domain.enums import ShiftStatus, TaskStatus, is_line_staff
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Shift, TaskInstance, TemplateTask

MAX_BATCH_SIZE = 50


@dataclass(frozen=True, slots=True)
class BatchCompletedTask:
    task_id: uuid.UUID
    status: str


@dataclass(frozen=True, slots=True)
class BatchCompleteResult:
    completed: list[BatchCompletedTask]


class CompleteTasksBatchUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        task_ids: list[uuid.UUID],
        user: CurrentUser,
    ) -> Result[BatchCompleteResult, DomainError]:
        if not task_ids:
            return Success(BatchCompleteResult(completed=[]))

        if len(task_ids) > MAX_BATCH_SIZE:
            return Failure(
                DomainError(
                    "too_many_tasks",
                    f"batch is limited to {MAX_BATCH_SIZE} tasks per request",
                )
            )

        # Deduplicate while preserving order.
        seen: set[uuid.UUID] = set()
        unique_ids = [tid for tid in task_ids if not (tid in seen or seen.add(tid))]  # type: ignore[func-returns-value]

        rows = (
            await self._session.execute(
                select(TaskInstance, TemplateTask, Shift)
                .join(TemplateTask, TemplateTask.id == TaskInstance.template_task_id)
                .join(Shift, Shift.id == TaskInstance.shift_id)
                .where(TaskInstance.id.in_(unique_ids))
            )
        ).all()

        if not rows:
            return Failure(DomainError("task_not_found", "no matching tasks found"))

        if len(rows) != len(unique_ids):
            return Failure(DomainError("task_not_found", "one or more task IDs not found"))

        # Validate shift state once (all tasks must share the same shift).
        first_shift: Shift = rows[0][2]
        if first_shift.operator_user_id is None:
            return Failure(DomainError("shift_not_claimed"))
        if is_line_staff(user.role) and first_shift.operator_user_id != user.id:
            return Failure(DomainError("not_your_shift"))
        if first_shift.status != ShiftStatus.ACTIVE:
            return Failure(DomainError("shift_not_active"))

        now = datetime.now(tz=UTC)
        completed: list[BatchCompletedTask] = []

        for task, template_task, shift in rows:
            if shift.id != first_shift.id:
                return Failure(DomainError("tasks_mixed_shifts", "all tasks must belong to the same shift"))

            if template_task.requires_comment:
                return Failure(
                    DomainError("task_requires_comment", f"task {task.id} requires a comment — use the single-task endpoint")
                )
            if task.status == TaskStatus.OBSOLETE:
                return Failure(DomainError("task_obsolete", f"task {task.id} is obsolete"))
            if task.status not in (TaskStatus.PENDING, TaskStatus.WAIVER_REJECTED):
                return Failure(
                    DomainError("task_not_in_pending_state", f"task {task.id} is already {task.status}")
                )

            task.status = TaskStatus.DONE.value
            task.completed_at = now
            completed.append(BatchCompletedTask(task_id=task.id, status=TaskStatus.DONE.value))

        photo_skipped = sum(
            1 for _task, tt, _shift in rows if tt.requires_photo
        )
        await write_audit(
            session=self._session,
            organization_id=user.organization_id,
            actor_user_id=user.id,
            event_type="task.batch_completed",
            payload={
                "shift_id": str(first_shift.id),
                "task_ids": [str(tid) for tid in unique_ids],
                "count": len(completed),
                **({"photo_skipped": photo_skipped} if photo_skipped else {}),
            },
        )
        await self._session.commit()

        # Fire real-time progress events for each completed task — fire-and-forget
        # so the HTTP response is not delayed by dispatcher sessions.
        from shiftops_api.infra.notifications.dispatcher import dispatch_task_progress

        for item in completed:
            _fire(
                dispatch_task_progress(
                    shift_id=first_shift.id,
                    task_id=item.task_id,
                    actor_user_id=user.id,
                    new_status=TaskStatus.DONE.value,
                )
            )

        return Success(BatchCompleteResult(completed=completed))
