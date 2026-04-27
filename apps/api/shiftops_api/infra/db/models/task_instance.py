from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shiftops_api.infra.db.base import Base
from shiftops_api.infra.db.mixins import TimestampMixin, UuidPkMixin


class TaskInstance(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "task_instances"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','done','skipped','waived','waiver_pending','waiver_rejected')",
            name="status_allowed",
        ),
    )

    shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shifts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("template_tasks.id", ondelete="RESTRICT"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    waiver_reason: Mapped[str | None] = mapped_column(String(64))
    waiver_description: Mapped[str | None] = mapped_column(Text)
    waiver_decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    waiver_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
