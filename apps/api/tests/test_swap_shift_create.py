"""Unit tests for swap-request creation validation (no DB)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.application.shifts.swap_shift_requests import CreateSwapShiftRequestUseCase
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import Failure


def _user(oid: uuid.UUID, uid: uuid.UUID) -> CurrentUser:
    return CurrentUser(
        id=uid,
        organization_id=oid,
        role=UserRole.OPERATOR,
        tg_user_id=None,
    )


@pytest.mark.asyncio
async def test_create_swap_rejects_same_shift_ids() -> None:
    oid = uuid.uuid4()
    uid = uuid.uuid4()
    sid = uuid.uuid4()
    me = _user(oid, uid)
    session = AsyncMock()
    use_case = CreateSwapShiftRequestUseCase(session=session)
    result = await use_case.execute(
        user=me,
        proposer_shift_id=sid,
        counterparty_shift_id=sid,
    )
    assert isinstance(result, Failure)
    assert result.error.code == "swap_same_shift"
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_create_swap_rejects_missing_shift() -> None:
    oid = uuid.uuid4()
    uid = uuid.uuid4()
    me = _user(oid, uid)
    session = AsyncMock()

    async def exec_side_effect(*_args, **_kwargs):
        r = MagicMock()
        r.scalar_one_or_none = lambda: None
        return r

    session.execute = AsyncMock(side_effect=exec_side_effect)
    use_case = CreateSwapShiftRequestUseCase(session=session)
    a, b = uuid.uuid4(), uuid.uuid4()
    result = await use_case.execute(
        user=me,
        proposer_shift_id=a,
        counterparty_shift_id=b,
    )
    assert isinstance(result, Failure)
    assert result.error.code == "shift_not_found"
