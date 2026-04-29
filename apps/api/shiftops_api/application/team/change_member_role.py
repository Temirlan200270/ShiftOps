"""Use case: change a member's role inside the current tenant.

Only role transitions between ``admin``, ``operator``, and ``bartender`` are
allowed here (not ``owner``):

- Promotion to / demotion of ``owner`` is a separate flow (single owner per
  org, see ``CreateOrganizationUseCase`` and bot's ``/org_set_owner``). This
  use case fails with ``cannot_change_owner_role`` if the *target* is owner,
  and with ``invalid_target_role`` if the caller asks to set role to owner.
- The same authorization guard as for deactivation applies: super-admin or
  org owner only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.application.team.permissions import can_manage_member
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import TelegramAccount, User

ManageableRole = Literal["admin", "operator", "bartender"]
_ALLOWED_NEW_ROLES: frozenset[str] = frozenset(
    {UserRole.ADMIN.value, UserRole.OPERATOR.value, UserRole.BARTENDER.value}
)


@dataclass(frozen=True, slots=True)
class MemberRoleChanged:
    user_id: uuid.UUID
    role: str
    no_op: bool


class ChangeMemberRoleUseCase:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        actor: CurrentUser,
        target_user_id: uuid.UUID,
        new_role: str,
    ) -> Result[MemberRoleChanged, DomainError]:
        new_role_norm = (new_role or "").strip().lower()
        if new_role_norm not in _ALLOWED_NEW_ROLES:
            return Failure(
                DomainError(
                    "invalid_target_role",
                    "role must be one of: admin, operator, bartender",
                )
            )

        target = await self._session.get(User, target_user_id)
        if target is None or target.organization_id != actor.organization_id:
            return Failure(DomainError("user_not_found", "unknown user in this organization"))

        if target.is_active is False:
            return Failure(DomainError("already_inactive", "user is inactive"))

        if target.role == UserRole.OWNER.value:
            return Failure(
                DomainError(
                    "cannot_change_owner_role",
                    "owner role is managed via /org_set_owner",
                )
            )

        target_tg_id = (
            await self._session.execute(
                select(TelegramAccount.tg_user_id).where(TelegramAccount.user_id == target.id)
            )
        ).scalar_one_or_none()

        allowed = can_manage_member(actor=actor, target=target, target_tg_id=target_tg_id)
        if isinstance(allowed, Failure):
            return allowed

        if target.role == new_role_norm:
            return Success(MemberRoleChanged(user_id=target.id, role=new_role_norm, no_op=True))

        target.role = new_role_norm
        await self._session.flush()
        return Success(MemberRoleChanged(user_id=target.id, role=new_role_norm, no_op=False))


async def evaluate_role_change_eligibility(
    *,
    actor: CurrentUser,
    target: User,
    session: AsyncSession,
) -> tuple[bool, str | None]:
    """Whether *actor* may change *target*'s role, with stable failure code."""

    if target.is_active is False:
        return False, "already_inactive"
    if target.role == UserRole.OWNER.value:
        return False, "cannot_change_owner_role"

    target_tg_id = (
        await session.execute(
            select(TelegramAccount.tg_user_id).where(TelegramAccount.user_id == target.id)
        )
    ).scalar_one_or_none()

    allowed = can_manage_member(actor=actor, target=target, target_tg_id=target_tg_id)
    if isinstance(allowed, Failure):
        return False, allowed.error.code
    return True, None
