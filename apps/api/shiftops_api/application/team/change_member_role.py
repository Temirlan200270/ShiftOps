"""Use case: change a member's role inside the current tenant.

Only role transitions between ``admin``, ``operator``, and ``bartender`` are
allowed here (not ``owner``):

- Promotion to / demotion of ``owner`` is a separate flow (single owner per
  org, see ``CreateOrganizationUseCase`` and bot's ``/org_set_owner``). This
  use case fails with ``cannot_change_owner_role`` if the *target* is owner,
  and with ``invalid_target_role`` if the caller asks to set role to owner.
- The same authorization guard as for deactivation applies: super-admin or
  org owner only.

Optional ``job_title`` (V1.1): display label only; omit the field in JSON to
leave the column unchanged, send ``null`` or ``""`` after trim to clear.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.audit import write_audit
from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.application.team.permissions import can_manage_member
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import TelegramAccount, User

ManageableRole = Literal["admin", "operator", "bartender"]
_ALLOWED_NEW_ROLES: frozenset[str] = frozenset(
    {UserRole.ADMIN.value, UserRole.OPERATOR.value, UserRole.BARTENDER.value}
)

_JOB_TITLE_MAX_LEN: Final[int] = 80


class _JobTitleUnset:
    """Sentinel: caller did not send ``job_title`` — do not modify the column."""


JOB_TITLE_UNCHANGED: Final[_JobTitleUnset] = _JobTitleUnset()


def _normalize_job_title(raw: str | None) -> str | None:
    """Trim; empty string becomes ``None`` (clear)."""

    if raw is None:
        return None
    s = raw.strip()
    return s or None


@dataclass(frozen=True, slots=True)
class MemberRoleChanged:
    user_id: uuid.UUID
    role: str
    job_title: str | None
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
        job_title: str | None | _JobTitleUnset = JOB_TITLE_UNCHANGED,
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

        if target.role == UserRole.OWNER:
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

        nj_norm: str | None | _JobTitleUnset = JOB_TITLE_UNCHANGED
        if job_title is not JOB_TITLE_UNCHANGED:
            nj_norm = _normalize_job_title(job_title)
            if nj_norm is not None and len(nj_norm) > _JOB_TITLE_MAX_LEN:
                return Failure(
                    DomainError(
                        "invalid_job_title",
                        f"job_title must be at most {_JOB_TITLE_MAX_LEN} characters",
                    )
                )

        old_role_str = target.role.value
        old_jt = target.job_title

        role_changes = old_role_str != new_role_norm
        jt_changes = False
        if nj_norm is not JOB_TITLE_UNCHANGED:
            assert not isinstance(nj_norm, _JobTitleUnset)
            jt_changes = (old_jt or None) != nj_norm

        if not role_changes and not jt_changes:
            return Success(
                MemberRoleChanged(
                    user_id=target.id,
                    role=new_role_norm,
                    job_title=old_jt,
                    no_op=True,
                )
            )

        if role_changes:
            target.role = new_role_norm
        if nj_norm is not JOB_TITLE_UNCHANGED:
            target.job_title = nj_norm

        await self._session.flush()

        audit_payload: dict[str, object] = {"target_user_id": str(target.id)}
        if role_changes:
            audit_payload["role"] = {"from": old_role_str, "to": new_role_norm}
        if nj_norm is not JOB_TITLE_UNCHANGED:
            audit_payload["job_title"] = {"from": old_jt, "to": nj_norm}

        await write_audit(
            session=self._session,
            organization_id=actor.organization_id,
            actor_user_id=actor.id,
            event_type="member.updated",
            payload=audit_payload,
        )

        return Success(
            MemberRoleChanged(
                user_id=target.id,
                role=new_role_norm,
                job_title=target.job_title,
                no_op=False,
            )
        )


async def evaluate_role_change_eligibility(
    *,
    actor: CurrentUser,
    target: User,
    session: AsyncSession,
) -> tuple[bool, str | None]:
    """Whether *actor* may change *target*'s role, with stable failure code."""

    if target.is_active is False:
        return False, "already_inactive"
    if target.role == UserRole.OWNER:
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
