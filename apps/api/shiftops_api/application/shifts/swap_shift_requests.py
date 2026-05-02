"""Peer swap of two scheduled shifts (exchange operator_user_id)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.audit import write_audit
from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.domain.enums import ShiftStatus
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Shift, ShiftSwapRequest, User

_SWAP_PENDING = "pending"
_SWAP_ACCEPTED = "accepted"
_SWAP_DECLINED = "declined"
_SWAP_CANCELLED = "cancelled"

_MAX_MSG = 280


@dataclass(frozen=True, slots=True)
class SwapRequestRowDTO:
    id: uuid.UUID
    status: str
    message: str | None
    created_at: datetime
    resolved_at: datetime | None
    proposer_user_id: uuid.UUID
    proposer_name: str
    counterparty_user_id: uuid.UUID
    counterparty_name: str
    proposer_shift_id: uuid.UUID
    counterparty_shift_id: uuid.UUID


def _normalize_msg(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    if len(s) > _MAX_MSG:
        return None
    return s


class CreateSwapShiftRequestUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        user: CurrentUser,
        proposer_shift_id: uuid.UUID,
        counterparty_shift_id: uuid.UUID,
        message: str | None = None,
    ) -> Result[uuid.UUID, DomainError]:
        msg = _normalize_msg(message)
        if message is not None and msg is None and message.strip():
            return Failure(DomainError("swap_message_too_long"))

        if proposer_shift_id == counterparty_shift_id:
            return Failure(DomainError("swap_same_shift"))

        s1 = (
            await self._session.execute(select(Shift).where(Shift.id == proposer_shift_id))
        ).scalar_one_or_none()
        s2 = (
            await self._session.execute(select(Shift).where(Shift.id == counterparty_shift_id))
        ).scalar_one_or_none()
        if s1 is None or s2 is None:
            return Failure(DomainError("shift_not_found"))
        if s1.organization_id != user.organization_id or s2.organization_id != user.organization_id:
            return Failure(DomainError("shift_not_found"))
        if s1.operator_user_id != user.id:
            return Failure(DomainError("swap_not_your_shift"))
        if s2.operator_user_id is None:
            return Failure(DomainError("swap_counterparty_unassigned"))
        if s2.operator_user_id == user.id:
            return Failure(DomainError("swap_invalid_counterparty"))
        if s1.status != ShiftStatus.SCHEDULED.value or s2.status != ShiftStatus.SCHEDULED.value:
            return Failure(DomainError("swap_not_scheduled"))

        counterparty_id = s2.operator_user_id

        row = ShiftSwapRequest(
            organization_id=user.organization_id,
            proposer_user_id=user.id,
            counterparty_user_id=counterparty_id,
            proposer_shift_id=proposer_shift_id,
            counterparty_shift_id=counterparty_shift_id,
            status=_SWAP_PENDING,
            message=msg,
            resolved_at=None,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            return Failure(DomainError("swap_duplicate_pending"))

        await write_audit(
            session=self._session,
            organization_id=user.organization_id,
            actor_user_id=user.id,
            event_type="shift.swap_requested",
            payload={
                "request_id": str(row.id),
                "proposer_shift_id": str(proposer_shift_id),
                "counterparty_shift_id": str(counterparty_shift_id),
            },
        )
        await self._session.commit()

        from shiftops_api.infra.notifications.dispatcher import dispatch_swap_request_created

        await dispatch_swap_request_created(request_id=row.id)
        return Success(row.id)


class AcceptSwapShiftRequestUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        user: CurrentUser,
        request_id: uuid.UUID,
    ) -> Result[None, DomainError]:
        req = (
            await self._session.execute(
                select(ShiftSwapRequest)
                .where(ShiftSwapRequest.id == request_id)
                .where(ShiftSwapRequest.organization_id == user.organization_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if req is None:
            return Failure(DomainError("swap_request_not_found"))
        if req.status != _SWAP_PENDING:
            return Failure(DomainError("swap_not_pending"))
        if req.counterparty_user_id != user.id:
            return Failure(DomainError("swap_not_counterparty"))

        s1 = (
            await self._session.execute(
                select(Shift)
                .where(Shift.id == req.proposer_shift_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        s2 = (
            await self._session.execute(
                select(Shift)
                .where(Shift.id == req.counterparty_shift_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if s1 is None or s2 is None:
            return Failure(DomainError("shift_not_found"))
        if s1.status != ShiftStatus.SCHEDULED.value or s2.status != ShiftStatus.SCHEDULED.value:
            return Failure(DomainError("swap_not_scheduled"))
        if s1.operator_user_id != req.proposer_user_id or s2.operator_user_id != req.counterparty_user_id:
            return Failure(DomainError("swap_shifts_changed"))

        op_a = s1.operator_user_id
        op_b = s2.operator_user_id
        s1.operator_user_id = op_b
        s2.operator_user_id = op_a

        req.status = _SWAP_ACCEPTED
        req.resolved_at = datetime.now(tz=UTC)

        await write_audit(
            session=self._session,
            organization_id=user.organization_id,
            actor_user_id=user.id,
            event_type="shift.swap_accepted",
            payload={
                "request_id": str(req.id),
                "proposer_shift_id": str(s1.id),
                "counterparty_shift_id": str(s2.id),
            },
        )
        await self._session.commit()

        from shiftops_api.infra.notifications.dispatcher import dispatch_swap_request_resolved

        await dispatch_swap_request_resolved(request_id=req.id, accepted=True)
        return Success(None)


class DeclineSwapShiftRequestUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        user: CurrentUser,
        request_id: uuid.UUID,
    ) -> Result[None, DomainError]:
        req = (
            await self._session.execute(
                select(ShiftSwapRequest)
                .where(ShiftSwapRequest.id == request_id)
                .where(ShiftSwapRequest.organization_id == user.organization_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if req is None:
            return Failure(DomainError("swap_request_not_found"))
        if req.status != _SWAP_PENDING:
            return Failure(DomainError("swap_not_pending"))
        if req.counterparty_user_id != user.id:
            return Failure(DomainError("swap_not_counterparty"))

        req.status = _SWAP_DECLINED
        req.resolved_at = datetime.now(tz=UTC)
        await self._session.commit()

        from shiftops_api.infra.notifications.dispatcher import dispatch_swap_request_resolved

        await dispatch_swap_request_resolved(request_id=req.id, accepted=False)
        return Success(None)


class CancelSwapShiftRequestUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        user: CurrentUser,
        request_id: uuid.UUID,
    ) -> Result[None, DomainError]:
        req = (
            await self._session.execute(
                select(ShiftSwapRequest)
                .where(ShiftSwapRequest.id == request_id)
                .where(ShiftSwapRequest.organization_id == user.organization_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if req is None:
            return Failure(DomainError("swap_request_not_found"))
        if req.status != _SWAP_PENDING:
            return Failure(DomainError("swap_not_pending"))
        if req.proposer_user_id != user.id:
            return Failure(DomainError("swap_not_proposer"))

        req.status = _SWAP_CANCELLED
        req.resolved_at = datetime.now(tz=UTC)
        await self._session.commit()
        return Success(None)


class ListSwapShiftRequestsUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        user: CurrentUser,
        direction: str,
    ) -> Result[list[SwapRequestRowDTO], DomainError]:
        stmt = select(ShiftSwapRequest).where(
            ShiftSwapRequest.organization_id == user.organization_id
        )
        if direction == "in":
            stmt = stmt.where(ShiftSwapRequest.counterparty_user_id == user.id)
        elif direction == "out":
            stmt = stmt.where(ShiftSwapRequest.proposer_user_id == user.id)
        else:
            return Failure(DomainError("invalid_direction"))

        stmt = stmt.order_by(ShiftSwapRequest.created_at.desc()).limit(50)
        rows = (await self._session.execute(stmt)).scalars().all()

        user_ids: set[uuid.UUID] = set()
        for r in rows:
            user_ids.add(r.proposer_user_id)
            user_ids.add(r.counterparty_user_id)
        users = {}
        if user_ids:
            urows = (
                await self._session.execute(select(User).where(User.id.in_(user_ids)))
            ).scalars().all()
            users = {u.id: u for u in urows}

        out: list[SwapRequestRowDTO] = []
        for r in rows:
            pu = users.get(r.proposer_user_id)
            cu = users.get(r.counterparty_user_id)
            out.append(
                SwapRequestRowDTO(
                    id=r.id,
                    status=r.status,
                    message=r.message,
                    created_at=r.created_at,
                    resolved_at=r.resolved_at,
                    proposer_user_id=r.proposer_user_id,
                    proposer_name=pu.full_name if pu else "?",
                    counterparty_user_id=r.counterparty_user_id,
                    counterparty_name=cu.full_name if cu else "?",
                    proposer_shift_id=r.proposer_shift_id,
                    counterparty_shift_id=r.counterparty_shift_id,
                )
            )
        return Success(out)


__all__ = [
    "AcceptSwapShiftRequestUseCase",
    "CancelSwapShiftRequestUseCase",
    "CreateSwapShiftRequestUseCase",
    "DeclineSwapShiftRequestUseCase",
    "ListSwapShiftRequestsUseCase",
    "SwapRequestRowDTO",
]
