"""Pure helpers for template claim RBAC."""

from __future__ import annotations

import uuid

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.application.shifts.claim_role import user_may_operate_template_role
from shiftops_api.domain.enums import UserRole


def _user(role: UserRole) -> CurrentUser:
    return CurrentUser(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role=role,
        tg_user_id=None,
    )


def test_operator_only_operator_templates() -> None:
    u = _user(UserRole.OPERATOR)
    assert user_may_operate_template_role(u, UserRole.OPERATOR)
    assert not user_may_operate_template_role(u, UserRole.BARTENDER)


def test_owner_any_template() -> None:
    u = _user(UserRole.OWNER)
    assert user_may_operate_template_role(u, UserRole.BARTENDER)


def test_admin_covers_line_templates() -> None:
    u = _user(UserRole.ADMIN)
    assert user_may_operate_template_role(u, UserRole.OPERATOR)
    assert user_may_operate_template_role(u, UserRole.BARTENDER)
    assert user_may_operate_template_role(u, UserRole.ADMIN)
