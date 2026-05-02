"""Context for deep-link swap invite (proposer shift encoded in /start swap_req_)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.domain.enums import ShiftStatus
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Location, Shift, Template, User


@dataclass(frozen=True, slots=True)
class SwapLinkPreviewDTO:
    shift_id: uuid.UUID
    template_name: str
    location_name: str
    scheduled_start: str
    scheduled_end: str
    station_label: str | None
    slot_index: int
    proposer_user_id: uuid.UUID
    proposer_full_name: str


class SwapLinkPreviewUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        user: CurrentUser,
        proposer_shift_id: uuid.UUID,
    ) -> Result[SwapLinkPreviewDTO, DomainError]:
        row = (
            await self._session.execute(
                select(Shift, Template, Location)
                .join(Template, Template.id == Shift.template_id)
                .join(Location, Location.id == Shift.location_id)
                .where(Shift.id == proposer_shift_id)
            )
        ).first()
        if row is None:
            return Failure(DomainError("shift_not_found"))
        shift, template, location = row
        if shift.organization_id != user.organization_id:
            return Failure(DomainError("shift_not_found"))
        if shift.status != ShiftStatus.SCHEDULED.value:
            return Failure(DomainError("swap_link_not_scheduled"))
        if shift.operator_user_id is None:
            return Failure(DomainError("swap_link_shift_unassigned"))
        operator = await self._session.get(User, shift.operator_user_id)
        if operator is None:
            return Failure(DomainError("swap_link_shift_unassigned"))
        return Success(
            SwapLinkPreviewDTO(
                shift_id=shift.id,
                template_name=template.name,
                location_name=location.name,
                scheduled_start=shift.scheduled_start.isoformat(),
                scheduled_end=shift.scheduled_end.isoformat(),
                station_label=shift.station_label,
                slot_index=int(shift.slot_index),
                proposer_user_id=operator.id,
                proposer_full_name=operator.full_name,
            )
        )


__all__ = ["SwapLinkPreviewDTO", "SwapLinkPreviewUseCase"]
