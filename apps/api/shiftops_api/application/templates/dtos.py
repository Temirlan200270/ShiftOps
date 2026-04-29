"""DTOs shared between the template CRUD use cases and the HTTP layer.

Design notes
------------
- Use cases speak Decimal/UUID/Enums; the HTTP layer converts to JSON via
  Pydantic. Keeping these as plain dataclasses lets domain code import them
  without pulling FastAPI / Pydantic into the application layer.
- ``TemplateTaskInputDTO`` deliberately omits ``id`` for creates; the
  use case generates it. For updates the caller may provide an existing id
  to preserve the row's history (e.g. completed shift instances pointing
  at it). When the id is absent we treat it as a brand-new task.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from shiftops_api.domain.enums import Criticality, UserRole

__all__ = [
    "TemplateDTO",
    "TemplateInputDTO",
    "TemplateListItemDTO",
    "TemplateTaskDTO",
    "TemplateTaskInputDTO",
]


@dataclass(frozen=True, slots=True)
class TemplateTaskInputDTO:
    title: str
    criticality: Criticality
    requires_photo: bool
    requires_comment: bool
    description: str | None = None
    # Free-form group label (e.g. "Кухня", "Зал"). Optional. Whitespace-only
    # strings are normalised to None by the use case so an accidental
    # padding does not create an empty group on the UI.
    section: str | None = None
    # Set to an existing template_tasks.id to preserve provenance through
    # an edit; leave None to create a fresh row.
    id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class TemplateInputDTO:
    name: str
    role_target: UserRole
    tasks: list[TemplateTaskInputDTO]


@dataclass(frozen=True, slots=True)
class TemplateTaskDTO:
    id: uuid.UUID
    title: str
    description: str | None
    section: str | None
    criticality: str
    requires_photo: bool
    requires_comment: bool
    order_index: int


@dataclass(frozen=True, slots=True)
class TemplateDTO:
    id: uuid.UUID
    name: str
    role_target: str
    tasks: list[TemplateTaskDTO]


@dataclass(frozen=True, slots=True)
class TemplateListItemDTO:
    id: uuid.UUID
    name: str
    role_target: str
    task_count: int
