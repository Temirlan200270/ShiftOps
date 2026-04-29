"""Authorization rules shared by team-management use cases.

Two facts decide who can act on a member:

1. Is the actor a *platform* super-admin? That is determined by their Telegram
   id (``settings.super_admin_tg_id``) — there is no such role in the DB. A
   super-admin can do anything except act on themselves.
2. Otherwise, only org *owners* can change roles or deactivate members. Org
   admins/operators cannot.

The same guard is used for both *change role* and *deactivate*: identical
authorization, different effects. Single rule = single source of truth and
single ``can_*`` flag in the API.
"""

from __future__ import annotations

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.config import get_settings
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import User


def is_platform_super_admin(actor: CurrentUser) -> bool:
    """True when the JWT-bound Telegram id matches ``super_admin_tg_id``.

    The check is done against the *issued* token, not against the database, so
    a downgrade (e.g. unsetting the env var) takes effect on the next login.
    """

    sid = get_settings().super_admin_tg_id
    return sid is not None and actor.tg_user_id == sid


def can_manage_member(
    *,
    actor: CurrentUser,
    target: User,
    target_tg_id: int | None,
) -> Result[None, DomainError]:
    """Whether *actor* may change the role of / deactivate *target*.

    Returns a stable failure code so the API and UI can render i18n strings:

    - ``cannot_manage_self`` — acting on yourself is never allowed.
    - ``cannot_manage_super_admin`` — the platform super-admin (matched by
      linked Telegram id) is protected from any tenant-level action.
    - ``insufficient_role`` — only org owners (or the platform super-admin)
      may manage members.
    """

    if actor.id == target.id:
        return Failure(DomainError("cannot_manage_self", "cannot act on yourself"))

    sid = get_settings().super_admin_tg_id
    if sid is not None and target_tg_id is not None and target_tg_id == sid:
        return Failure(
            DomainError(
                "cannot_manage_super_admin",
                "platform super-admin cannot be managed via tenant API",
            )
        )

    if is_platform_super_admin(actor):
        return Success(None)

    if actor.role == UserRole.OWNER:
        return Success(None)

    return Failure(DomainError("insufficient_role", "only owner or super-admin"))
