"""Pure-rules tests for :class:`ChangeMemberRoleUseCase` guards.

The DB-touching code paths are exercised by integration tests; here we focus
on the deterministic predicate ``can_manage_member`` plus the role-transition
constraints that live entirely in the use case (no IO).
"""

from __future__ import annotations

import uuid

import pytest

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.application.team.permissions import can_manage_member
from shiftops_api.config import get_settings
from shiftops_api.domain.enums import UserRole


class _UserLike:
    def __init__(self, *, uid: uuid.UUID, role: str, active: bool = True) -> None:
        self.id = uid
        self.role = role
        self.is_active = active


def _actor(*, uid: uuid.UUID, org: uuid.UUID, role: UserRole, tg: int | None = None) -> CurrentUser:
    return CurrentUser(id=uid, organization_id=org, role=role, tg_user_id=tg)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()


def test_owner_can_manage_admin_and_operator() -> None:
    org = uuid.uuid4()
    actor = _actor(uid=uuid.uuid4(), org=org, role=UserRole.OWNER)
    for role in ("admin", "operator"):
        target = _UserLike(uid=uuid.uuid4(), role=role)
        r = can_manage_member(actor=actor, target=target, target_tg_id=None)  # type: ignore[arg-type]
        assert getattr(r, "error", None) is None


def test_admin_cannot_manage_anyone() -> None:
    org = uuid.uuid4()
    actor = _actor(uid=uuid.uuid4(), org=org, role=UserRole.ADMIN)
    for role in ("owner", "admin", "operator"):
        target = _UserLike(uid=uuid.uuid4(), role=role)
        r = can_manage_member(actor=actor, target=target, target_tg_id=None)  # type: ignore[arg-type]
        assert r.error.code == "insufficient_role"


def test_operator_cannot_manage_anyone() -> None:
    org = uuid.uuid4()
    actor = _actor(uid=uuid.uuid4(), org=org, role=UserRole.OPERATOR)
    target = _UserLike(uid=uuid.uuid4(), role="operator")
    r = can_manage_member(actor=actor, target=target, target_tg_id=None)  # type: ignore[arg-type]
    assert r.error.code == "insufficient_role"


def test_cannot_manage_self() -> None:
    org = uuid.uuid4()
    uid = uuid.uuid4()
    actor = _actor(uid=uid, org=org, role=UserRole.OWNER)
    target = _UserLike(uid=uid, role="owner")
    r = can_manage_member(actor=actor, target=target, target_tg_id=None)  # type: ignore[arg-type]
    assert r.error.code == "cannot_manage_self"


def test_cannot_manage_super_admin_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPER_ADMIN_TG_ID", "9001")
    get_settings.cache_clear()
    org = uuid.uuid4()
    actor = _actor(uid=uuid.uuid4(), org=org, role=UserRole.OWNER)
    target = _UserLike(uid=uuid.uuid4(), role="admin")
    r = can_manage_member(actor=actor, target=target, target_tg_id=9001)  # type: ignore[arg-type]
    assert r.error.code == "cannot_manage_super_admin"


def test_super_admin_actor_can_manage_anyone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPER_ADMIN_TG_ID", "9001")
    get_settings.cache_clear()
    org = uuid.uuid4()
    actor = _actor(uid=uuid.uuid4(), org=org, role=UserRole.ADMIN, tg=9001)
    for role in ("owner", "admin", "operator"):
        target = _UserLike(uid=uuid.uuid4(), role=role)
        r = can_manage_member(actor=actor, target=target, target_tg_id=None)  # type: ignore[arg-type]
        assert getattr(r, "error", None) is None


def test_super_admin_cannot_manage_self(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPER_ADMIN_TG_ID", "9001")
    get_settings.cache_clear()
    org = uuid.uuid4()
    uid = uuid.uuid4()
    actor = _actor(uid=uid, org=org, role=UserRole.OWNER, tg=9001)
    target = _UserLike(uid=uid, role="owner")
    r = can_manage_member(actor=actor, target=target, target_tg_id=9001)  # type: ignore[arg-type]
    assert r.error.code == "cannot_manage_self"
