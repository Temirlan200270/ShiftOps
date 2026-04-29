"""Pydantic schema for ``organizations.business_hours`` JSONB.

Two buckets:

- ``regular`` — weekly recurring windows (e.g. Mon–Sun 09:00–23:00).
- ``dated`` — one-off calendar dates with open/close times (holidays, events).

Timezone is optional metadata for the owner's reference; enforcement of
shift times still lives on ``locations.timezone`` and CSV/recurrence flows.
"""

from __future__ import annotations

import re
from datetime import date, time
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

_HHMM_RE = re.compile(r"^\d{2}:\d{2}$")
_MAX_REGULAR = 24
_MAX_DATED = 366


def _parse_hhmm(s: str) -> time:
    if not _HHMM_RE.match(s):
        raise ValueError("time must be HH:MM")
    h, m = int(s[:2]), int(s[3:5])
    if h > 23 or m > 59:
        raise ValueError("invalid clock time")
    return time(h, m)


class RegularHoursRow(BaseModel):
    """Recurring weekly opening hours."""

    weekdays: list[int] = Field(default_factory=list, description="ISO weekdays 1–7")
    opens: str = Field(min_length=5, max_length=5)
    closes: str = Field(min_length=5, max_length=5)

    @field_validator("weekdays", mode="before")
    @classmethod
    def _norm_weekdays(cls, v: object) -> list[int]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise TypeError("weekdays must be a list of integers")
        out: list[int] = []
        for x in v:
            i = int(x)
            if not 1 <= i <= 7:
                raise ValueError("weekday must be 1..7 (ISO)")
            out.append(i)
        dedup = sorted(set(out))
        if not dedup:
            raise ValueError("at least one weekday is required")
        return dedup

    @field_validator("opens", "closes")
    @classmethod
    def _validate_times(cls, v: str) -> str:
        _parse_hhmm(v)
        return v

    @model_validator(mode="after")
    def _not_identical(self) -> RegularHoursRow:
        if self.opens == self.closes:
            raise ValueError("opens and closes must differ")
        return self


class DatedHoursRow(BaseModel):
    """Single calendar day override (public holiday, private event, etc.)."""

    on: date
    opens: str = Field(min_length=5, max_length=5)
    closes: str = Field(min_length=5, max_length=5)
    note: str | None = Field(default=None, max_length=256)

    @field_validator("opens", "closes")
    @classmethod
    def _validate_times(cls, v: str) -> str:
        _parse_hhmm(v)
        return v

    @model_validator(mode="after")
    def _not_identical(self) -> DatedHoursRow:
        if self.opens == self.closes:
            raise ValueError("opens and closes must differ")
        return self


class BusinessHoursConfig(BaseModel):
    """Root document stored in ``organizations.business_hours``."""

    timezone: str | None = Field(default=None, max_length=64)
    regular: list[RegularHoursRow] = Field(default_factory=list)
    dated: list[DatedHoursRow] = Field(default_factory=list)

    @field_validator("timezone", mode="before")
    @classmethod
    def _empty_tz_none(cls, v: object) -> str | None:
        if v is None or v == "":
            return None
        if not isinstance(v, str):
            raise TypeError("timezone must be a string or null")
        return v.strip() or None

    @model_validator(mode="after")
    def _limits(self) -> BusinessHoursConfig:
        if len(self.regular) > _MAX_REGULAR:
            raise ValueError(f"at most {_MAX_REGULAR} regular rows")
        if len(self.dated) > _MAX_DATED:
            raise ValueError(f"at most {_MAX_DATED} dated rows")
        return self

    def to_storage(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def parse_storage(cls, raw: dict[str, Any] | None) -> BusinessHoursConfig:
        if not raw:
            return cls()
        return cls.model_validate(raw)


__all__ = [
    "BusinessHoursConfig",
    "DatedHoursRow",
    "RegularHoursRow",
]
