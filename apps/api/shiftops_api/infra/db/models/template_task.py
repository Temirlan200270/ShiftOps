from __future__ import annotations

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shiftops_api.infra.db.base import Base
from shiftops_api.infra.db.mixins import UuidPkMixin


class TemplateTask(UuidPkMixin, Base):
    __tablename__ = "template_tasks"
    __table_args__ = (
        CheckConstraint(
            "criticality IN ('critical','required','optional')",
            name="criticality_allowed",
        ),
    )

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # Optional human-readable group label ("Кухня", "Зал", "Бар"). NULL when
    # the template has no sections — the renderer falls back to a flat list.
    section: Mapped[str | None] = mapped_column(String(64), nullable=True)
    criticality: Mapped[str] = mapped_column(String(16), nullable=False, default="required")
    requires_photo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_comment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
