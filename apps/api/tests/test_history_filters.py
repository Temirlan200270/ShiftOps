"""Pure-rules tests for the history endpoint's filter / RBAC guard.

The use case mostly emits SQL — covered by integration tests with a real
Postgres. What we *can* unit-test deterministically is the authorization
predicate and the range-validation guard, because they each fail before
the SQL ever runs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.application.shifts.list_history import ListHistoryUseCase
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import Failure


def _user(role: UserRole) -> CurrentUser:
    return CurrentUser(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role=role,
        tg_user_id=None,
    )


@pytest.mark.asyncio
async def test_line_staff_cannot_target_other_user() -> None:
    """An operator who passes ``target_user_id`` for a teammate must be
    rejected before any DB call. The use case enforces this at the
    boundary so the FastAPI handler can return a clean 403.
    """
    use_case = ListHistoryUseCase(session=AsyncMock())
    me = _user(UserRole.OPERATOR)
    result = await use_case.execute(
        user=me,
        target_user_id=uuid.uuid4(),  # not me
    )
    assert isinstance(result, Failure)
    assert result.error.code == "forbidden"


@pytest.mark.asyncio
async def test_line_staff_passing_own_id_is_allowed() -> None:
    """A bartender who explicitly passes their own id must NOT be 403'd.
    This was a bug we shipped once — the boundary check was using
    ``target_user_id is not None`` instead of ``!= user.id``.
    """
    session = AsyncMock()
    # The select() chain is awaited; we intercept and return an empty
    # result so we don't have to model SQLAlchemy's mappings.
    fake_exec_result = AsyncMock()
    fake_exec_result.all = lambda: []
    session.execute.return_value = fake_exec_result
    use_case = ListHistoryUseCase(session=session)
    me = _user(UserRole.BARTENDER)
    result = await use_case.execute(user=me, target_user_id=me.id)
    # Should NOT be forbidden. May still bail later for unrelated reasons,
    # but we only assert on the early-return path here.
    if isinstance(result, Failure):
        assert result.error.code != "forbidden"


@pytest.mark.asyncio
async def test_invalid_range_when_to_is_before_from() -> None:
    use_case = ListHistoryUseCase(session=AsyncMock())
    rt = datetime(2026, 4, 1, tzinfo=UTC)
    rf = datetime(2026, 5, 1, tzinfo=UTC)
    result = await use_case.execute(
        user=_user(UserRole.OWNER),
        date_from=rf,
        date_to=rt,
    )
    assert isinstance(result, Failure)
    assert result.error.code == "invalid_range"


@pytest.mark.asyncio
async def test_admin_can_target_any_operator() -> None:
    """Admins / owners pass ``target_user_id`` freely — that's the whole
    point of the drill-down feature. No early 403 here.
    """
    session = AsyncMock()
    fake_exec_result = AsyncMock()
    fake_exec_result.all = lambda: []
    session.execute.return_value = fake_exec_result
    use_case = ListHistoryUseCase(session=session)
    admin = _user(UserRole.ADMIN)
    result = await use_case.execute(user=admin, target_user_id=uuid.uuid4())
    if isinstance(result, Failure):
        assert result.error.code != "forbidden"
