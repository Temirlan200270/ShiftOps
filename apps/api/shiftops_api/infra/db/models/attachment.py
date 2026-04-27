from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shiftops_api.infra.db.base import Base
from shiftops_api.infra.db.mixins import TimestampMixin, UuidPkMixin


class Attachment(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint(
            "storage_provider IN ('telegram','r2')",
            name="storage_provider_allowed",
        ),
        CheckConstraint(
            "capture_method IN ('camera','fallback','unknown')",
            name="capture_method_allowed",
        ),
    )

    task_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    storage_provider: Mapped[str] = mapped_column(String(16), nullable=False, default="telegram")

    tg_file_id: Mapped[str | None] = mapped_column(String(255))
    tg_file_unique_id: Mapped[str | None] = mapped_column(String(64))
    tg_archive_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    tg_archive_message_id: Mapped[int | None] = mapped_column(BigInteger)

    r2_object_key: Mapped[str | None] = mapped_column(String(512))

    mime: Mapped[str] = mapped_column(String(64), nullable=False, default="image/jpeg")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    phash: Mapped[str | None] = mapped_column(String(32))
    suspicious: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    capture_method: Mapped[str] = mapped_column(String(16), nullable=False, default="camera")
    geo: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    captured_at_server: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
