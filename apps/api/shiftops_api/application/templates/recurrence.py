"""Recurrence config persisted in ``Template.default_schedule``.

Why this lives in the application layer
---------------------------------------
The DB column is JSONB precisely because the recurrence model evolves
faster than schema migrations. Pydantic gives us a single source of
truth for shape + validation; the JSONB cell holds whatever the
current version emits, and we keep a ``kind`` discriminator so future
``weekly``/``cron`` variants can coexist with the v1 ``daily`` shape.

Validated facts a recurrence config holds:

- WHAT — the template (its tasks become the shift task instances).
- WHEN — local time of day, weekdays (ISO 1..7), tz of the location.
- WHERE — exactly one ``location_id`` (recurrence is per-template per
  location; multi-location ownership uses one config per template
  copy).
- WHO — optional ``default_assignee_id``. When unset the use case
  falls back to the first owner of the org so the shift always has an
  ``operator_user_id`` (the schema requires it).

The shift's ``scheduled_end`` = ``scheduled_start + duration_min``;
inputs that wrap past midnight (e.g. open at 23:00, duration 360
minutes) just spill into the next UTC day, which is fine for
analytics and CSV exports alike.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import time
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from shiftops_api.domain.timezone import require_iana_timezone

ISO_WEEKDAYS = {1, 2, 3, 4, 5, 6, 7}


class RecurrenceConfig(BaseModel):
    """JSONB-backed recurrence rules. Stored in ``Template.default_schedule``."""

    kind: Literal["daily"] = "daily"
    auto_create: bool = False
    # ISO 8601 ``HH:MM`` form when transported. Pydantic parses ``str`` and
    # ``time`` interchangeably so the JSONB cell can stash either; we
    # canonicalise to ``time`` in code.
    time_of_day: time
    duration_min: int = Field(ge=15, le=24 * 60)
    weekdays: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7])
    timezone: str = Field(min_length=1, max_length=64)
    location_id: uuid.UUID
    default_assignee_id: uuid.UUID | None = None
    # How many minutes BEFORE ``time_of_day`` we are allowed to materialise
    # the shift. 0 means "create at exactly time_of_day"; 60 means "create
    # an hour earlier so the operator sees their checklist when they
    # arrive". The cron tick will create as soon as the lead window opens.
    lead_time_min: int = Field(default=0, ge=0, le=12 * 60)

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            return require_iana_timezone(value)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("weekdays")
    @classmethod
    def _validate_weekdays(cls, value: list[int]) -> list[int]:
        bad = [v for v in value if v not in ISO_WEEKDAYS]
        if bad:
            raise ValueError(f"weekdays must be 1..7 (ISO), got {bad!r}")
        if not value:
            raise ValueError("weekdays cannot be empty when auto_create=true")
        # Stable order, dedup. Avoids "[7,1,1,1]" footguns.
        return sorted(set(value))

    def to_storage(self) -> dict[str, Any]:
        """Serialize to a JSONB-friendly dict."""

        return {
            "kind": self.kind,
            "auto_create": self.auto_create,
            "time_of_day": self.time_of_day.strftime("%H:%M"),
            "duration_min": self.duration_min,
            "weekdays": list(self.weekdays),
            "timezone": self.timezone,
            "location_id": str(self.location_id),
            "default_assignee_id": (
                str(self.default_assignee_id) if self.default_assignee_id else None
            ),
            "lead_time_min": self.lead_time_min,
        }


@dataclass(frozen=True, slots=True)
class RecurrenceInputDTO:
    """Plain-old-data shadow used by the application layer.

    The HTTP layer parses with Pydantic; the use case takes this DTO so
    domain code does not transitively depend on Pydantic.
    """

    auto_create: bool
    time_of_day: time
    duration_min: int
    weekdays: list[int]
    timezone: str
    location_id: uuid.UUID
    default_assignee_id: uuid.UUID | None
    lead_time_min: int


def parse_storage(blob: dict[str, Any] | None) -> RecurrenceConfig | None:
    """Inverse of ``to_storage``: round-trip from JSONB.

    Returns ``None`` when the cell is empty, malformed, or describes a
    non-``daily`` variant. The cron tick treats this as "skip" so a
    bad row in the DB never bricks the worker.
    """

    if not blob:
        return None
    if blob.get("kind", "daily") != "daily":
        return None
    try:
        return RecurrenceConfig.model_validate(blob)
    except Exception:  # noqa: BLE001 — caller treats None as "ignore"
        return None


__all__ = [
    "ISO_WEEKDAYS",
    "RecurrenceConfig",
    "RecurrenceInputDTO",
    "parse_storage",
]
