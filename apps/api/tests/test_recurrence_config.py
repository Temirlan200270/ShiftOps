"""Validation rules for ``RecurrenceConfig``.

These tests do *not* hit the database — they exercise the Pydantic
contract that protects the JSONB cell from malformed inputs.
``CreateRecurringShiftsTickUseCase`` is covered separately in
``test_recurring_shifts_tick.py``.
"""

from __future__ import annotations

import uuid
from datetime import time

import pytest

from shiftops_api.application.templates.recurrence import (
    RecurrenceConfig,
    parse_storage,
)


def _base(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "kind": "daily",
        "auto_create": True,
        "time_of_day": time(9, 0),
        "duration_min": 480,
        "weekdays": [1, 2, 3, 4, 5, 6, 7],
        "timezone": "Asia/Almaty",
        "location_id": uuid.uuid4(),
        "default_assignee_id": None,
        "lead_time_min": 30,
    }
    base.update(overrides)
    return base


def test_weekdays_dedup_and_sorted() -> None:
    cfg = RecurrenceConfig.model_validate(_base(weekdays=[7, 1, 1, 1, 3]))
    assert cfg.weekdays == [1, 3, 7]


def test_invalid_weekday_rejected() -> None:
    with pytest.raises(Exception):
        RecurrenceConfig.model_validate(_base(weekdays=[0, 8]))


def test_empty_weekdays_rejected() -> None:
    with pytest.raises(Exception):
        RecurrenceConfig.model_validate(_base(weekdays=[]))


def test_duration_bounds() -> None:
    with pytest.raises(Exception):
        RecurrenceConfig.model_validate(_base(duration_min=10))
    with pytest.raises(Exception):
        RecurrenceConfig.model_validate(_base(duration_min=24 * 60 + 1))


def test_to_storage_round_trip() -> None:
    cfg = RecurrenceConfig.model_validate(_base())
    blob = cfg.to_storage()
    parsed = parse_storage(blob)
    assert parsed is not None
    assert parsed.weekdays == cfg.weekdays
    assert parsed.timezone == cfg.timezone
    assert parsed.time_of_day == cfg.time_of_day


def test_parse_storage_returns_none_on_garbage() -> None:
    assert parse_storage(None) is None
    assert parse_storage({}) is None
    assert parse_storage({"kind": "weekly", "auto_create": False}) is None


def test_time_of_day_accepts_string() -> None:
    cfg = RecurrenceConfig.model_validate(_base(time_of_day="23:30"))
    assert cfg.time_of_day == time(23, 30)
