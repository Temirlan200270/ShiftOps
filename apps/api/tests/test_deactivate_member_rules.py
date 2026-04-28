from __future__ import annotations

import uuid

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.application.team.deactivate_member import _can_deactivate
from shiftops_api.domain.enums import UserRole


class _UserLike:
    def __init__(self, *, uid: uuid.UUID, role: str, active: bool) -> None:
        self.id = uid
        self.role = role
        self.is_active = active


def _actor(*, uid: uuid.UUID, org: uuid.UUID, role: UserRole) -> CurrentUser:
    return CurrentUser(id=uid, organization_id=org, role=role, tg_user_id=None)


def test_owner_can_deactivate_admin_operator_owner() -> None:
    org = uuid.uuid4()
    actor = _actor(uid=uuid.uuid4(), org=org, role=UserRole.OWNER)
    for role in ("owner", "admin", "operator"):
        target = _UserLike(uid=uuid.uuid4(), role=role, active=True)
        r = _can_deactivate(actor=actor, target=target)  # type: ignore[arg-type]
        assert getattr(r, "error", None) is None


def test_admin_can_only_deactivate_operator() -> None:
    org = uuid.uuid4()
    actor = _actor(uid=uuid.uuid4(), org=org, role=UserRole.ADMIN)

    ok = _UserLike(uid=uuid.uuid4(), role="operator", active=True)
    assert getattr(_can_deactivate(actor=actor, target=ok), "error", None) is None  # type: ignore[arg-type]

    for role in ("admin", "owner"):
        target = _UserLike(uid=uuid.uuid4(), role=role, active=True)
        r = _can_deactivate(actor=actor, target=target)  # type: ignore[arg-type]
        assert r.error.code == "insufficient_role"


def test_cannot_deactivate_self() -> None:
    org = uuid.uuid4()
    uid = uuid.uuid4()
    actor = _actor(uid=uid, org=org, role=UserRole.OWNER)
    target = _UserLike(uid=uid, role="owner", active=True)
    r = _can_deactivate(actor=actor, target=target)  # type: ignore[arg-type]
    assert r.error.code == "cannot_deactivate_self"


def test_cannot_deactivate_inactive_user() -> None:
    org = uuid.uuid4()
    actor = _actor(uid=uuid.uuid4(), org=org, role=UserRole.OWNER)
    target = _UserLike(uid=uuid.uuid4(), role="operator", active=False)
    r = _can_deactivate(actor=actor, target=target)  # type: ignore[arg-type]
    assert r.error.code == "already_inactive"

