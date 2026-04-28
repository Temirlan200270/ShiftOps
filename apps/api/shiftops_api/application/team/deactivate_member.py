"""Use case: soft-delete (deactivate) a member in the current tenant.

Rules:
- owner can deactivate anyone in their org (except self / platform super-admin)
- admin can deactivate only operators
- cannot deactivate yourself
- cannot deactivate platform super-admin (by tg_user_id) if that account is linked in the org
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.config import get_settings
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import TelegramAccount, User


@dataclass(frozen=True, slots=True)
class MemberDeactivated:
    user_id: uuid.UUID


def _can_deactivate(*, actor: CurrentUser, target: User) -> Result[None, DomainError]:
    if actor.id == target.id:
        return Failure(DomainError("cannot_deactivate_self", "cannot deactivate yourself"))

    if target.is_active is False:
        return Failure(DomainError("already_inactive", "user already inactive"))

    if actor.role == UserRole.ADMIN and target.role != UserRole.OPERATOR.value:
        return Failure(DomainError("insufficient_role", "admin can deactivate only operators"))

    if actor.role not in (UserRole.ADMIN, UserRole.OWNER):
        return Failure(DomainError("insufficient_role", "only admin/owner can deactivate members"))

    return Success(None)


class DeactivateMemberUseCase:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        actor: CurrentUser,
        target_user_id: uuid.UUID,
    ) -> Result[MemberDeactivated, DomainError]:
        # `users` is tenant-scoped via RLS (app.org_id already set by require_user).
        target = await self._session.get(User, target_user_id)
        if target is None or target.organization_id != actor.organization_id:
            return Failure(DomainError("user_not_found", "unknown user in this organization"))

        allowed = _can_deactivate(actor=actor, target=target)
        if isinstance(allowed, Failure):
            return allowed

        # Protect the platform super-admin if linked into this tenant.
        sid = get_settings().super_admin_tg_id
        if sid is not None:
            row = (
                await self._session.execute(
                    select(TelegramAccount.tg_user_id).where(TelegramAccount.user_id == target.id)
                )
            ).scalar_one_or_none()
            if row == sid:
                return Failure(
                    DomainError("cannot_deactivate_super_admin", "cannot deactivate platform super-admin")
                )

        target.is_active = False
        await self._session.flush()
        return Success(MemberDeactivated(user_id=target.id))


async def evaluate_deactivation_eligibility(
    *,
    actor: CurrentUser,
    target: User,
    session: AsyncSession,
) -> tuple[bool, str | None]:
    """Whether *actor* may deactivate *target*, with a stable failure code for UI."""
    allowed = _can_deactivate(actor=actor, target=target)
    if isinstance(allowed, Failure):
        return False, allowed.error.code

    sid = get_settings().super_admin_tg_id
    if sid is not None:
        row = (
            await session.execute(
                select(TelegramAccount.tg_user_id).where(TelegramAccount.user_id == target.id)
            )
        ).scalar_one_or_none()
        if row == sid:
            return False, "cannot_deactivate_super_admin"
    return True, None

