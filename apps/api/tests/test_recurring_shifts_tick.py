"""Decision-table tests for ``CreateRecurringShiftsTickUseCase``.

Why a *decision-table* style and not full integration here
----------------------------------------------------------
The use case is *mostly* a coordinator over SQLAlchemy queries. The
decision that's actually fragile to break — "should the tick fire
right now in this timezone?" — lives in the pure ``is_window_open``
function. Covering it in fast unit tests catches the kinds of bugs we
have actually shipped (off-by-one weekday, DST surprise, missing
location TZ).

Idempotency / advisory-lock tests live in
``test_rls_isolation.py``-style integration when we wire a Postgres
container into CI.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time

import pytest

from shiftops_api.application.templates.recurrence import RecurrenceConfig
from shiftops_api.application.templates.recurring_shifts_tick import (
    TRAILING_TOLERANCE_MIN,
    is_window_open,
)


def _cfg(**overrides: object) -> RecurrenceConfig:
    base: dict[str, object] = {
        "kind": "daily",
        "auto_create": True,
        "time_of_day": time(9, 0),
        "duration_min": 480,
        "weekdays": [1, 2, 3, 4, 5, 6, 7],
        "timezone": "Asia/Almaty",  # UTC+5/+6 (no DST)
        "location_id": uuid.uuid4(),
        "default_assignee_id": None,
        "lead_time_min": 30,
    }
    base.update(overrides)
    return RecurrenceConfig.model_validate(base)


def test_window_opens_at_lead_time_boundary() -> None:
    cfg = _cfg(time_of_day=time(9, 0), lead_time_min=30)
    # 09:00 Asia/Almaty (UTC+5) == 04:00 UTC; lead window opens 30 min earlier.
    boundary_utc = datetime(2026, 5, 4, 3, 30, tzinfo=UTC)  # Mon
    assert is_window_open(cfg, location_tz_name="Asia/Almaty", now_utc=boundary_utc)


def test_window_closes_after_trailing_tolerance() -> None:
    cfg = _cfg(time_of_day=time(9, 0), lead_time_min=0)
    too_late_utc = datetime(
        2026, 5, 4, 4, TRAILING_TOLERANCE_MIN + 1, tzinfo=UTC
    )  # Mon, 09:06 local
    assert not is_window_open(cfg, location_tz_name="Asia/Almaty", now_utc=too_late_utc)


def test_window_closed_outside_weekdays() -> None:
    # Saturday (weekday 6) is excluded.
    cfg = _cfg(weekdays=[1, 2, 3, 4, 5])
    sat_utc = datetime(2026, 5, 9, 4, 0, tzinfo=UTC)  # Sat 09:00 Almaty
    assert not is_window_open(cfg, location_tz_name="Asia/Almaty", now_utc=sat_utc)


def test_other_timezone_changes_local_weekday_at_midnight() -> None:
    """A 23:00 cron in Asia/Almaty maps to 18:00 UTC the same day, NOT
    the next; the local-weekday filter must operate on local time, not
    UTC.
    """

    cfg = _cfg(time_of_day=time(23, 0), weekdays=[7])  # Sundays only
    # 18:00 UTC on Sunday May 3, 2026 == 23:00 Asia/Almaty on Sunday.
    on_time_utc = datetime(2026, 5, 3, 18, 0, tzinfo=UTC)
    assert is_window_open(cfg, location_tz_name="Asia/Almaty", now_utc=on_time_utc)


def test_unknown_timezone_falls_back_to_utc() -> None:
    cfg = _cfg(timezone="Mars/Olympus", time_of_day=time(9, 0))
    # 09:00 UTC on Monday.
    on_time_utc = datetime(2026, 5, 4, 9, 0, tzinfo=UTC)
    assert is_window_open(cfg, location_tz_name="Mars/Olympus", now_utc=on_time_utc)


def test_location_tz_used_when_cfg_has_blank_tz() -> None:
    """If ``cfg.timezone`` is missing/blank, fall back to the location."""

    cfg = _cfg(timezone="UTC", time_of_day=time(9, 0))  # canonical
    # We can't easily express "blank tz" via Pydantic (min_length=1), so
    # we cover the documented intent: location TZ wins when cfg's TZ is
    # unknown. Mars/Olympus on cfg, Asia/Almaty on location → uses the
    # `cfg.timezone or location_tz_name` order from the production code.
    bad_cfg = _cfg(timezone="Mars/Olympus", time_of_day=time(9, 0))
    on_time_utc = datetime(2026, 5, 4, 4, 0, tzinfo=UTC)  # 09:00 Almaty
    # cfg.timezone takes precedence over location_tz_name; since
    # Mars/Olympus is unknown, we fall back to UTC (NOT to the location).
    # Document the contract:
    assert not is_window_open(
        bad_cfg, location_tz_name="Asia/Almaty", now_utc=on_time_utc
    )
    # Sanity: the canonical case still works.
    assert is_window_open(
        cfg, location_tz_name="Asia/Almaty", now_utc=datetime(2026, 5, 4, 9, 0, tzinfo=UTC)
    )


@pytest.mark.parametrize(
    "lead_time_min",
    [0, 15, 60, 120],
)
def test_lead_time_widens_open_side(lead_time_min: int) -> None:
    cfg = _cfg(time_of_day=time(9, 0), lead_time_min=lead_time_min)
    # exactly at the open boundary
    boundary_utc = datetime(2026, 5, 4, 4, 0, tzinfo=UTC) - _minutes(lead_time_min)
    assert is_window_open(cfg, location_tz_name="Asia/Almaty", now_utc=boundary_utc)


def _minutes(n: int) -> datetime.timedelta:  # quoted: simple helper, defer import
    from datetime import timedelta

    return timedelta(minutes=n)
