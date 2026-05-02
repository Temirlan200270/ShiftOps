"""Operator's upcoming scheduled shifts (for swap UI)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.domain.enums import ShiftStatus
from shiftops_api.domain.result import DomainError, Result, Success
from shiftops_api.infra.db.models import Location, Shift, Template


@dataclass(frozen=True, slots=True)
class MyScheduledShiftDTO:
    id: uuid.UUID
    template_name: str
    location_name: str
    scheduled_start: datetime
    scheduled_end: datetime
    station_label: str | None
    slot_index: int


class ListMyScheduledShiftsUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        user: CurrentUser,
    ) -> Result[list[MyScheduledShiftDTO], DomainError]:
        stmt = (
            select(Shift, Template, Location)
            .join(Template, Template.id == Shift.template_id)
            .join(Location, Location.id == Shift.location_id)
            .where(Shift.organization_id == user.organization_id)
            .where(Shift.operator_user_id == user.id)
            .where(Shift.status == ShiftStatus.SCHEDULED.value)
            .order_by(Shift.scheduled_start.asc())
        )
        rows = (await self._session.execute(stmt)).all()
        items = [
            MyScheduledShiftDTO(
                id=s.id,
                template_name=tpl.name,
                location_name=loc.name,
                scheduled_start=s.scheduled_start,
                scheduled_end=s.scheduled_end,
                station_label=s.station_label,
                slot_index=int(s.slot_index),
            )
            for s, tpl, loc in rows
        ]
        return Success(items)


__all__ = ["ListMyScheduledShiftsUseCase", "MyScheduledShiftDTO"]
