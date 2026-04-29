"""Domain enums.

Stored as `text` with `CHECK` constraints in Postgres (see DATABASE_SCHEMA.md
for rationale). Mapped to `enum.StrEnum` here for type safety in Python.
"""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    OPERATOR = "operator"
    BARTENDER = "bartender"


# Roles that execute assigned shifts (checklists) like operators.
LINE_STAFF_ROLES: frozenset[UserRole] = frozenset((UserRole.OPERATOR, UserRole.BARTENDER))


def is_line_staff(role: UserRole) -> bool:
    return role in LINE_STAFF_ROLES


class Criticality(StrEnum):
    CRITICAL = "critical"
    REQUIRED = "required"
    OPTIONAL = "optional"


class ShiftStatus(StrEnum):
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    CLOSED_CLEAN = "closed_clean"
    CLOSED_WITH_VIOLATIONS = "closed_with_violations"
    ABORTED = "aborted"


class TaskStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    SKIPPED = "skipped"
    WAIVED = "waived"
    WAIVER_PENDING = "waiver_pending"
    WAIVER_REJECTED = "waiver_rejected"


class StorageKind(StrEnum):
    TELEGRAM = "telegram"
    R2 = "r2"


class CaptureMethod(StrEnum):
    CAMERA = "camera"
    FALLBACK = "fallback"
    UNKNOWN = "unknown"
