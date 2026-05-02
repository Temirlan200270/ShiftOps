"""Scheduled pool slots without an operator that need admin attention."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.config import get_settings
from shiftops_api.domain.enums import ShiftStatus, UserRole
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Location, Shift, Template

VacantRiskKind = Literal["overdue", "unclaimed_started", "ending_soon"]


@dataclass(frozen=True, slots=True)
class VacantAtRiskDTO:
    shift_id: uuid.UUID
    location_id: uuid.UUID
    location_name: str
    template_name: str
    scheduled_start: datetime
    scheduled_end: datetime
    station_label: str | None
    slot_index: int
    kind: VacantRiskKind


class ListVacantAtRiskShiftsUseCase:
    def __init__(self, *, session: AsyncSession, now: datetime | None = None) -> None:
        self._session = session
        self._now = (now or datetime.now(tz=UTC)).astimezone(UTC)
        self._horizon = timedelta(minutes=get_settings().live_vacant_horizon_min)

    async def execute(self, *, user: CurrentUser) -> Result[list[VacantAtRiskDTO], DomainError]:
        if user.role not in (UserRole.ADMIN, UserRole.OWNER):
            return Failure(DomainError("forbidden"))

        now = self._now
        horizon_end = now + self._horizon

        stmt = (
            select(Shift, Location, Template)
            .join(Location, Location.id == Shift.location_id)
            .join(Template, Template.id == Shift.template_id)
            .where(Shift.status == ShiftStatus.SCHEDULED.value)
            .where(Shift.operator_user_id.is_(None))
            .where(
                or_(
                    Shift.scheduled_end <= horizon_end,
                    Shift.scheduled_start < now,
                )
            )
            .order_by(Shift.scheduled_end.asc())
        )
        rows = (await self._session.execute(stmt)).all()
        items: list[VacantAtRiskDTO] = []
        for shift, loc, tpl in rows:
            kind = _classify_kind(
                now=now,
                scheduled_start=shift.scheduled_start,
                scheduled_end=shift.scheduled_end,
                horizon_end=horizon_end,
            )
            items.append(
                VacantAtRiskDTO(
                    shift_id=shift.id,
                    location_id=loc.id,
                    location_name=loc.name,
                    template_name=tpl.name,
                    scheduled_start=shift.scheduled_start,
                    scheduled_end=shift.scheduled_end,
                    station_label=shift.station_label,
                    slot_index=int(shift.slot_index),
                    kind=kind,
                )
            )
        return Success(items)


def _classify_kind(
    *,
    now: datetime,
    scheduled_start: datetime,
    scheduled_end: datetime,
    horizon_end: datetime,
) -> VacantRiskKind:
    if scheduled_end < now:
        return "overdue"
    if scheduled_start < now:
        return "unclaimed_started"
    if scheduled_end <= horizon_end:
        return "ending_soon"
    return "ending_soon"


__all__ = [
    "ListVacantAtRiskShiftsUseCase",
    "VacantAtRiskDTO",
    "VacantRiskKind",
]
