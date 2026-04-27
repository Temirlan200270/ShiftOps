"""Use-case: admin approves or rejects a waiver request from a Telegram callback.

Triggered by the bot's `callback_query` handler (`waiver:<task_id>:approve`
/ `waiver:<task_id>:reject`). The bot translates the TG admin into a domain
user via the `telegram_accounts` lookup before calling this.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.audit import write_audit
from shiftops_api.domain.enums import TaskStatus, UserRole
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Shift, TaskInstance, User


@dataclass(frozen=True, slots=True)
class WaiverDecided:
    task_id: uuid.UUID
    final_status: str


class ApproveWaiverUseCase:
    """Approves OR rejects — `decision: approve | reject`."""

    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        task_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        decision: str,
    ) -> Result[WaiverDecided, DomainError]:
        if decision not in {"approve", "reject"}:
            return Failure(DomainError("invalid_decision"))

        admin = (
            await self._session.execute(select(User).where(User.id == admin_user_id))
        ).scalar_one_or_none()
        if admin is None:
            return Failure(DomainError("admin_not_found"))
        if admin.role not in {UserRole.ADMIN, UserRole.OWNER}:
            return Failure(DomainError("not_an_admin"))

        row = (
            await self._session.execute(
                select(TaskInstance, Shift)
                .join(Shift, Shift.id == TaskInstance.shift_id)
                .where(TaskInstance.id == task_id)
            )
        ).first()
        if row is None:
            return Failure(DomainError("task_not_found"))

        task, shift = row

        if shift.organization_id != admin.organization_id:
            return Failure(DomainError("cross_tenant_decision"))

        if task.status != TaskStatus.WAIVER_PENDING:
            return Failure(DomainError("task_not_in_waiver_pending"))

        new_status = TaskStatus.WAIVED if decision == "approve" else TaskStatus.WAIVER_REJECTED
        task.status = new_status.value
        task.waiver_decided_by = admin.id
        task.waiver_decided_at = datetime.now(tz=timezone.utc)

        await write_audit(
            session=self._session,
            organization_id=shift.organization_id,
            actor_user_id=admin.id,
            event_type=f"waiver.{decision}",
            payload={"task_id": str(task.id)},
        )
        await self._session.commit()

        from shiftops_api.infra.notifications.dispatcher import dispatch_waiver_decision

        await dispatch_waiver_decision(
            task_id=task.id,
            decision=decision,
            decided_by=admin.id,
        )

        return Success(WaiverDecided(task_id=task.id, final_status=new_status.value))
