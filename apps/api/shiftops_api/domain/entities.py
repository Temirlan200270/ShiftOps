"""Domain entities — pure dataclasses, no IO, no SQLAlchemy.

These are the shapes use-cases work with. Repositories convert ORM rows into
these and back.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .enums import CaptureMethod, Criticality, ShiftStatus, StorageKind, TaskStatus, UserRole


@dataclass(frozen=True, slots=True)
class Organization:
    id: uuid.UUID
    name: str
    plan: str
    is_active: bool
    trial_ends_at: datetime | None


@dataclass(frozen=True, slots=True)
class Location:
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    timezone: str
    tg_admin_chat_id: int | None


@dataclass(frozen=True, slots=True)
class User:
    id: uuid.UUID
    organization_id: uuid.UUID
    role: UserRole
    full_name: str
    locale: str
    tg_user_id: int | None = None
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class Template:
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    role_target: UserRole
    slot_count: int = 1
    unassigned_pool: bool = False


@dataclass(frozen=True, slots=True)
class TemplateTask:
    id: uuid.UUID
    template_id: uuid.UUID
    title: str
    description: str | None
    criticality: Criticality
    requires_photo: bool
    requires_comment: bool
    order_index: int


@dataclass(frozen=True, slots=True)
class Shift:
    id: uuid.UUID
    organization_id: uuid.UUID
    location_id: uuid.UUID
    template_id: uuid.UUID
    operator_user_id: uuid.UUID | None
    scheduled_start: datetime
    scheduled_end: datetime
    actual_start: datetime | None
    actual_end: datetime | None
    status: ShiftStatus
    score: Decimal | None


@dataclass(frozen=True, slots=True)
class TaskInstance:
    id: uuid.UUID
    shift_id: uuid.UUID
    template_task_id: uuid.UUID
    status: TaskStatus
    waiver_reason: str | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class Attachment:
    id: uuid.UUID
    task_instance_id: uuid.UUID
    storage_provider: StorageKind
    tg_file_id: str | None
    tg_archive_chat_id: int | None
    tg_archive_message_id: int | None
    r2_object_key: str | None
    mime: str
    size_bytes: int
    phash: str | None
    suspicious: bool
    capture_method: CaptureMethod
    captured_at_server: datetime
