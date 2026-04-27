"""Use-case: operator starts a scheduled shift.

Side effects:
- shift.status: scheduled -> active, actual_start = now()
- audit_event "shift.started"
- enqueues "shift_opened" notification to admin group + owner
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.audit import write_audit
from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.domain.enums import ShiftStatus, UserRole
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Shift


@dataclass(frozen=True, slots=True)
class StartedShift:
    id: uuid.UUID


class StartShiftUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        shift_id: uuid.UUID,
        user: CurrentUser,
    ) -> Result[StartedShift, DomainError]:
        shift = (
            await self._session.execute(select(Shift).where(Shift.id == shift_id))
        ).scalar_one_or_none()
        if shift is None:
            return Failure(DomainError("shift_not_found"))

        if user.role == UserRole.OPERATOR and shift.operator_user_id != user.id:
            return Failure(DomainError("not_your_shift"))

        if shift.status != ShiftStatus.SCHEDULED:
            return Failure(DomainError("shift_not_scheduled"))

        shift.status = ShiftStatus.ACTIVE.value
        shift.actual_start = datetime.now(tz=timezone.utc)

        await write_audit(
            session=self._session,
            organization_id=user.organization_id,
            actor_user_id=user.id,
            event_type="shift.started",
            payload={"shift_id": str(shift.id), "location_id": str(shift.location_id)},
        )
        await self._session.commit()

        # Lazy import keeps the use-case independent of the queue at type level.
        from shiftops_api.infra.notifications.dispatcher import dispatch_shift_opened

        await dispatch_shift_opened(shift_id=shift.id)

        return Success(StartedShift(id=shift.id))
