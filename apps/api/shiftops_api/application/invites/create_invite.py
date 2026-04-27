"""Use case: create a one-time invite (deep-link token) for org onboarding."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Invite, Location

_DEFAULT_HOURS = 48
_MAX_HOURS = 168
# URL-safe token; fits Telegram ?start= payload limits. MVP: store plaintext
# with UNIQUE — post-MVP consider SHA-256(token) at rest for DB-leak safety.
_TOKEN_BYTES = 24


@dataclass(frozen=True, slots=True)
class InviteCreated:
    id: uuid.UUID
    token: str
    expires_at: datetime


def _coerce_role(role: str) -> UserRole | None:
    try:
        u = UserRole(role)
    except ValueError:
        return None
    if u in (UserRole.OWNER,):
        return None
    if u in (UserRole.ADMIN, UserRole.OPERATOR):
        return u
    return None


class CreateInviteUseCase:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        user: CurrentUser,
        role: str,
        location_id: uuid.UUID | None,
        expires_in_hours: int | None,
    ) -> Result[InviteCreated, DomainError]:
        target = _coerce_role(role)
        if target is None:
            return Failure(
                DomainError("invalid_invite_role", "role must be admin or operator")
            )

        if user.role == UserRole.ADMIN and target == UserRole.ADMIN:
            return Failure(
                DomainError(
                    "invite_admin_requires_owner",
                    "only an owner can invite an admin",
                )
            )
        if user.role == UserRole.OPERATOR:
            return Failure(
                DomainError("insufficient_role", "operators cannot create invites")
            )

        hours = _DEFAULT_HOURS if expires_in_hours is None else expires_in_hours
        if hours < 1 or hours > _MAX_HOURS:
            return Failure(
                DomainError(
                    "invalid_expires_in_hours",
                    f"must be between 1 and {_MAX_HOURS}",
                )
            )

        if location_id is not None:
            loc = await self._session.get(Location, location_id)
            if loc is None or loc.organization_id != user.organization_id:
                return Failure(DomainError("location_not_found", "unknown location for org"))
        elif target == UserRole.OPERATOR:
            # Admins/owners can still invite an operator org-wide; location is optional
            # metadata. If you require a location, enforce non-null here.
            pass

        token = secrets.token_urlsafe(_TOKEN_BYTES)
        expires = datetime.now(tz=UTC) + timedelta(hours=hours)

        invite = Invite(
            id=uuid.uuid4(),
            organization_id=user.organization_id,
            location_id=location_id,
            role=target.value,
            token=token,
            created_by=user.id,
            expires_at=expires,
        )
        self._session.add(invite)
        await self._session.flush()
        return Success(
            InviteCreated(id=invite.id, token=token, expires_at=invite.expires_at)
        )
