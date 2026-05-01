"""Vacant scheduled shifts the caller may claim (pool model)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.application.shifts.claim_role import user_may_operate_template_role
from shiftops_api.domain.enums import ShiftStatus
from shiftops_api.domain.result import DomainError, Result, Success
from shiftops_api.infra.db.models import Location, Shift, Template


@dataclass(frozen=True, slots=True)
class VacantShiftDTO:
    id: uuid.UUID
    template_name: str
    template_id: uuid.UUID
    role_target: str
    location_id: uuid.UUID
    location_name: str
    scheduled_start: str
    scheduled_end: str
    station_label: str | None
    slot_index: int


class ListAvailableShiftsUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        user: CurrentUser,
        location_id: uuid.UUID | None = None,
    ) -> Result[list[VacantShiftDTO], DomainError]:
        stmt = (
            select(Shift, Template, Location)
            .join(Template, Template.id == Shift.template_id)
            .join(Location, Location.id == Shift.location_id)
            .where(Shift.organization_id == user.organization_id)
            .where(Shift.status == ShiftStatus.SCHEDULED.value)
            .where(Shift.operator_user_id.is_(None))
            .order_by(Shift.scheduled_start.asc(), Shift.slot_index.asc())
        )
        if location_id is not None:
            stmt = stmt.where(Shift.location_id == location_id)

        rows = (await self._session.execute(stmt)).all()
        out: list[VacantShiftDTO] = []
        for shift, tpl, loc in rows:
            if not user_may_operate_template_role(user, tpl.role_target):
                continue
            out.append(
                VacantShiftDTO(
                    id=shift.id,
                    template_name=tpl.name,
                    template_id=tpl.id,
                    role_target=str(tpl.role_target),
                    location_id=loc.id,
                    location_name=loc.name,
                    scheduled_start=shift.scheduled_start.astimezone(UTC).isoformat(),
                    scheduled_end=shift.scheduled_end.astimezone(UTC).isoformat(),
                    station_label=shift.station_label,
                    slot_index=shift.slot_index,
                )
            )
        return Success(out)
