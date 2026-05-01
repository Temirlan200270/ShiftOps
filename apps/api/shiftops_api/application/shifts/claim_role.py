"""Who may claim / execute a shift for a template ``role_target``."""

from __future__ import annotations

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.domain.enums import UserRole


def user_may_operate_template_role(user: CurrentUser, template_role: UserRole | str) -> bool:
    """Whether ``user`` may claim or run checklists for ``template_role``.

    Owners may claim any template; admins cover admin/operator/bartender/owner-target
    templates; line staff only their own role band.
    """

    tr = template_role if isinstance(template_role, UserRole) else UserRole(template_role)
    if user.role == UserRole.OWNER:
        return True
    if user.role == UserRole.ADMIN:
        # Deputy can cover owner-target opening/closing checklists too (small orgs).
        return tr in (
            UserRole.ADMIN,
            UserRole.OPERATOR,
            UserRole.BARTENDER,
            UserRole.OWNER,
        )
    if user.role == UserRole.OPERATOR:
        return tr == UserRole.OPERATOR
    if user.role == UserRole.BARTENDER:
        return tr == UserRole.BARTENDER
    return False
