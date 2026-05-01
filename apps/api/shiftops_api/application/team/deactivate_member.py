"""Use case: soft-delete (deactivate) a member in the current tenant.

Authorization is delegated to :func:`can_manage_member` so the rules stay in
sync with :class:`ChangeMemberRoleUseCase`. In short: only org owner or the
platform super-admin (matched by Telegram id) can deactivate; nobody can
deactivate themselves; nobody can deactivate the platform super-admin.

Owners may deactivate other owners (e.g. successor scenarios via
``/org_set_owner``); admins/operators have no such power.

The Telegram link (``telegram_accounts``) is kept so the same person can be
**reactivated** when they redeem a new invite for this organization
(see :class:`~shiftops_api.application.invites.redeem_invite.RedeemInviteUseCase`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.application.team.permissions import can_manage_member
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import TelegramAccount, User

_log = structlog.get_logger("shiftops.team")


@dataclass(frozen=True, slots=True)
class MemberDeactivated:
    user_id: uuid.UUID


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

        if target.is_active is False:
            return Failure(DomainError("already_inactive", "user already inactive"))

        target_tg_id = (
            await self._session.execute(
                select(TelegramAccount.tg_user_id).where(TelegramAccount.user_id == target.id)
            )
        ).scalar_one_or_none()

        allowed = can_manage_member(actor=actor, target=target, target_tg_id=target_tg_id)
        if isinstance(allowed, Failure):
            return allowed

        target.is_active = False
        await self._session.flush()
        _log.info(
            "team.member_deactivated",
            target_user_id=str(target.id),
            actor_user_id=str(actor.id),
            organization_id=str(actor.organization_id),
            target_role=target.role,
        )
        return Success(MemberDeactivated(user_id=target.id))


async def evaluate_deactivation_eligibility(
    *,
    actor: CurrentUser,
    target: User,
    session: AsyncSession,
) -> tuple[bool, str | None]:
    """Whether *actor* may deactivate *target*, with a stable failure code for UI."""

    if target.is_active is False:
        return False, "already_inactive"

    target_tg_id = (
        await session.execute(
            select(TelegramAccount.tg_user_id).where(TelegramAccount.user_id == target.id)
        )
    ).scalar_one_or_none()

    allowed = can_manage_member(actor=actor, target=target, target_tg_id=target_tg_id)
    if isinstance(allowed, Failure):
        return False, allowed.error.code
    return True, None
