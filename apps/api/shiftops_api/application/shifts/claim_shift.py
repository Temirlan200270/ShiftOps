"""Atomically claim a vacant scheduled shift (pool model) and open it."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.audit import write_audit
from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.application.shifts.claim_role import user_may_operate_template_role
from shiftops_api.application.shifts.geo import extract_geo_point, haversine_m
from shiftops_api.config import get_settings
from shiftops_api.domain.enums import ShiftStatus
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Location, Shift, Template


@dataclass(frozen=True, slots=True)
class ClaimedShift:
    id: uuid.UUID


class ClaimShiftUseCase:
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
    ) -> Result[ClaimedShift, DomainError]:
        shift = (
            await self._session.execute(select(Shift).where(Shift.id == shift_id))
        ).scalar_one_or_none()
        if shift is None:
            return Failure(DomainError("shift_not_found"))

        if shift.organization_id != user.organization_id:
            return Failure(DomainError("shift_not_found"))

        tpl = await self._session.get(Template, shift.template_id)
        if tpl is None:
            return Failure(DomainError("shift_not_found"))

        if not user_may_operate_template_role(user, tpl.role_target):
            return Failure(DomainError("insufficient_role"))

        if shift.status != ShiftStatus.SCHEDULED:
            return Failure(DomainError("shift_not_scheduled"))

        if shift.operator_user_id is not None:
            return Failure(DomainError("shift_taken"))

        now = datetime.now(tz=UTC)
        # Single atomic UPDATE: avoids a torn state if the process dies between
        # assigning operator and flipping status (and matches the race contract).
        claim_stmt = (
            update(Shift)
            .where(Shift.id == shift_id)
            .where(Shift.organization_id == user.organization_id)
            .where(Shift.operator_user_id.is_(None))
            .where(Shift.status == ShiftStatus.SCHEDULED.value)
            .values(
                operator_user_id=user.id,
                status=ShiftStatus.ACTIVE.value,
                actual_start=now,
            )
        )
        res = await self._session.execute(claim_stmt)
        if res.rowcount == 0:
            return Failure(DomainError("shift_taken"))

        shift = (
            await self._session.execute(select(Shift).where(Shift.id == shift_id))
        ).scalar_one()

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
            "claimed": True,
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

        return Success(ClaimedShift(id=shift.id))
