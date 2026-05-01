"""IANA timezone validation shared by API models and recurrence config."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def require_iana_timezone(name: str) -> str:
    """Return a normalised IANA id or raise ValueError."""
    key = (name or "").strip()
    if not key:
        raise ValueError("timezone must be non-empty")
    try:
        ZoneInfo(key)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown IANA timezone: {key!r}") from exc
    return key
