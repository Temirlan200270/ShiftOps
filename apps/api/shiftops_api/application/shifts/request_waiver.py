"""Use-case: operator requests a waiver for a critical / required task."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.audit import write_audit
from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.domain.enums import ShiftStatus, TaskStatus, UserRole
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Shift, TaskInstance, TemplateTask


_ALLOWED_REASONS = {"broken", "no_staff", "no_stock", "other"}


@dataclass(frozen=True, slots=True)
class WaiverPending:
    task_id: uuid.UUID


class RequestWaiverUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        task_id: uuid.UUID,
        user: CurrentUser,
        reason: str,
        description: str | None,
    ) -> Result[WaiverPending, DomainError]:
        if reason not in _ALLOWED_REASONS:
            return Failure(DomainError("invalid_reason"))

        row = (
            await self._session.execute(
                select(TaskInstance, TemplateTask, Shift)
                .join(TemplateTask, TemplateTask.id == TaskInstance.template_task_id)
                .join(Shift, Shift.id == TaskInstance.shift_id)
                .where(TaskInstance.id == task_id)
            )
        ).first()
        if row is None:
            return Failure(DomainError("task_not_found"))

        task, _template_task, shift = row

        if user.role == UserRole.OPERATOR and shift.operator_user_id != user.id:
            return Failure(DomainError("not_your_shift"))

        if shift.status != ShiftStatus.ACTIVE:
            return Failure(DomainError("shift_not_active"))

        if task.status != TaskStatus.PENDING:
            return Failure(DomainError("task_not_pending"))

        task.status = TaskStatus.WAIVER_PENDING.value
        task.waiver_reason = reason
        task.waiver_description = description

        await write_audit(
            session=self._session,
            organization_id=user.organization_id,
            actor_user_id=user.id,
            event_type="waiver.requested",
            payload={"task_id": str(task.id), "reason": reason},
        )
        await self._session.commit()

        from shiftops_api.infra.notifications.dispatcher import dispatch_waiver_request

        await dispatch_waiver_request(
            task_id=task.id,
            shift_id=shift.id,
            actor_user_id=user.id,
            reason=reason,
        )

        return Success(WaiverPending(task_id=task.id))
