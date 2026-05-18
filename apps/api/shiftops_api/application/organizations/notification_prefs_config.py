"""Validated Pydantic model for ``Organization.notification_prefs`` JSONB.

Structure (all fields optional, unrecognised keys are ignored):

    {
        "checklist_overdue": {
            "enabled": true,
            "delay_min": 60,
            "repeat_min": 5,
            "max_alerts": 12
        }
    }

``delay_min`` — minutes after ``scheduled_start`` before the first alert.
``repeat_min`` — minutes between subsequent alerts.
``max_alerts`` — hard ceiling on total alerts per shift (stops spam on very
    long or forgotten shifts).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChecklistOverduePrefs(BaseModel):
    enabled: bool = True
    delay_min: int = Field(default=60, ge=10, le=480)
    repeat_min: int = Field(default=5, ge=1, le=60)
    max_alerts: int = Field(default=12, ge=1, le=48)


class NotificationPrefsConfig(BaseModel):
    checklist_overdue: ChecklistOverduePrefs = Field(
        default_factory=ChecklistOverduePrefs
    )

    @classmethod
    def parse_storage(cls, raw: dict[str, Any]) -> "NotificationPrefsConfig":
        """Lenient parse: unknown keys are ignored, missing keys use defaults."""
        return cls.model_validate(raw)

    def to_storage(self) -> dict[str, Any]:
        return self.model_dump()


__all__ = ["ChecklistOverduePrefs", "NotificationPrefsConfig"]
