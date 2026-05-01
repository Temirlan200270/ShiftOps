"""Use-case: operator starts a scheduled shift.

Side effects:
- shift.status: scheduled -> active, actual_start = now()
- audit_event "shift.started"
- enqueues "shift_opened" notification to admin group + owner
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.audit import write_audit
from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.application.shifts.geo import extract_geo_point, haversine_m
from shiftops_api.config import get_settings
from shiftops_api.domain.enums import ShiftStatus, is_line_staff
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Location, Shift


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
        client_latitude: float | None = None,
        client_longitude: float | None = None,
        client_accuracy_m: float | None = None,
    ) -> Result[StartedShift, DomainError]:
        shift = (
            await self._session.execute(select(Shift).where(Shift.id == shift_id))
        ).scalar_one_or_none()
        if shift is None:
            return Failure(DomainError("shift_not_found"))

        if is_line_staff(user.role) and shift.operator_user_id != user.id:
            return Failure(DomainError("not_your_shift"))

        if shift.status != ShiftStatus.SCHEDULED:
            return Failure(DomainError("shift_not_scheduled"))

        shift.status = ShiftStatus.ACTIVE.value
        shift.actual_start = datetime.now(tz=UTC)

        location = await self._session.get(Location, shift.location_id)
        suspicious_location = False
        distance_m: float | None = None
        ref = extract_geo_point(location.geo if location else None)
        settings = get_settings()
        if (
            ref is not None
            and client_latitude is not None
            and client_longitude is not None
        ):
            distance_m = haversine_m(client_latitude, client_longitude, ref[0], ref[1])
            if distance_m > settings.shift_start_geo_warn_radius_m:
                suspicious_location = True

        audit_payload: dict = {
            "shift_id": str(shift.id),
            "location_id": str(shift.location_id),
            "suspicious_location": suspicious_location,
        }
        if distance_m is not None:
            audit_payload["distance_m"] = round(distance_m, 1)
            audit_payload["geo_threshold_m"] = settings.shift_start_geo_warn_radius_m
        if client_latitude is not None and client_longitude is not None:
            audit_payload["client_lat"] = round(client_latitude, 5)
            audit_payload["client_lon"] = round(client_longitude, 5)
        if client_accuracy_m is not None:
            audit_payload["client_accuracy_m"] = round(client_accuracy_m, 1)

        await write_audit(
            session=self._session,
            organization_id=user.organization_id,
            actor_user_id=user.id,
            event_type="shift.started",
            payload=audit_payload,
        )
        await self._session.commit()

        from shiftops_api.infra.notifications.dispatcher import dispatch_shift_opened

        await dispatch_shift_opened(shift_id=shift.id)

        return Success(StartedShift(id=shift.id))
