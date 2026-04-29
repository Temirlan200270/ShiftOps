"""Super-admin use case: create an invite without an existing user.

This is used by the Telegram bot for platform operations:
- create an org without owner
- issue a one-time invite for the first owner/admin/operator

It bypasses RLS (same pattern as auth exchange / invite redeem).
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Invite, Location, Organization

_DEFAULT_HOURS = 48
_MAX_HOURS = 168
_TOKEN_BYTES = 24


@dataclass(frozen=True, slots=True)
class SystemInviteCreated:
    id: uuid.UUID
    token: str
    expires_at: datetime


def _coerce_role(role: str) -> UserRole | None:
    try:
        return UserRole(role)
    except ValueError:
        return None


class CreateSystemInviteUseCase:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        organization_id: uuid.UUID,
        role: str,
        location_id: uuid.UUID | None,
        expires_in_hours: int | None,
    ) -> Result[SystemInviteCreated, DomainError]:
        target = _coerce_role(role)
        if target is None:
            return Failure(
                DomainError("invalid_invite_role", "role must be owner/admin/operator/bartender")
            )

        hours = _DEFAULT_HOURS if expires_in_hours is None else expires_in_hours
        if hours < 1 or hours > _MAX_HOURS:
            return Failure(
                DomainError(
                    "invalid_expires_in_hours",
                    f"must be between 1 and {_MAX_HOURS}",
                )
            )

        await self._session.execute(text("SET LOCAL row_security = off"))

        org = await self._session.get(Organization, organization_id)
        if org is None:
            return Failure(DomainError("org_not_found", "unknown organization"))

        if location_id is not None:
            loc = await self._session.get(Location, location_id)
            if loc is None or loc.organization_id != organization_id:
                return Failure(DomainError("location_not_found", "unknown location for org"))

        token = secrets.token_urlsafe(_TOKEN_BYTES)
        expires = datetime.now(tz=UTC) + timedelta(hours=hours)
        invite = Invite(
            id=uuid.uuid4(),
            organization_id=organization_id,
            location_id=location_id,
            role=target.value,
            token=token,
            created_by=None,
            expires_at=expires,
        )
        self._session.add(invite)
        await self._session.flush()
        return Success(SystemInviteCreated(id=invite.id, token=token, expires_at=invite.expires_at))

