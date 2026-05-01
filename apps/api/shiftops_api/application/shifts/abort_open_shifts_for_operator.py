"""Abort scheduled/active shifts for an operator.

When someone is soft-deactivated or re-seated via a new invite (new role), any
in-flight ``scheduled`` / ``active`` rows would still match
``ListMyShiftUseCase`` (``operator_user_id``) and show the wrong checklist.
Marking them ``aborted`` keeps ``GET /v1/shifts/me`` consistent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.domain.enums import ShiftStatus
from shiftops_api.infra.db.models import Shift


async def abort_open_shifts_for_operator(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    operator_user_id: uuid.UUID,
) -> None:
    now = datetime.now(tz=UTC)
    await session.execute(
        update(Shift)
        .where(Shift.organization_id == organization_id)
        .where(Shift.operator_user_id == operator_user_id)
        .where(
            Shift.status.in_(
                (ShiftStatus.SCHEDULED.value, ShiftStatus.ACTIVE.value),
            )
        )
        .values(
            status=ShiftStatus.ABORTED.value,
            actual_end=now,
        )
    )
