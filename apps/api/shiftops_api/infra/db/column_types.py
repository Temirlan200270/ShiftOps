"""Shared SQLAlchemy types for columns.

``UserRole`` is a :class:`enum.StrEnum`; the database stores lowercase values
(``owner``, …) per CHECK constraints. ``SAEnum`` defaults to persisting member
*names* unless ``values_callable`` is set — a single shared type avoids that
footgun when mapping ``UserRole`` in new models.
"""

from __future__ import annotations

from sqlalchemy import Enum as SAEnum

from shiftops_api.domain.enums import UserRole

user_role_db = SAEnum(
    UserRole,
    native_enum=False,
    validate_strings=True,
    values_callable=lambda obj: [e.value for e in obj],
)
