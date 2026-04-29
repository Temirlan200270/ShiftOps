from __future__ import annotations

import pytest

from shiftops_api.application.organizations.business_hours_config import (
    BusinessHoursConfig,
    RegularHoursRow,
)


def test_empty_storage_round_trip() -> None:
    cfg = BusinessHoursConfig.parse_storage({})
    assert cfg.regular == []
    assert cfg.dated == []
    assert cfg.timezone is None


def test_regular_weekdays_sorted_deduped() -> None:
    row = RegularHoursRow(weekdays=[5, 1, 5], opens="09:00", closes="22:00")
    assert row.weekdays == [1, 5]


def test_rejects_identical_open_close() -> None:
    with pytest.raises(ValueError):
        RegularHoursRow(weekdays=[1], opens="10:00", closes="10:00")


def test_dump_json_includes_dated_on_key() -> None:
    cfg = BusinessHoursConfig(
        timezone="Asia/Almaty",
        regular=[RegularHoursRow(weekdays=[1, 2], opens="09:00", closes="23:00")],
        dated=[],
    )
    d = cfg.to_storage()
    assert d["timezone"] == "Asia/Almaty"
    assert d["regular"][0]["weekdays"] == [1, 2]
