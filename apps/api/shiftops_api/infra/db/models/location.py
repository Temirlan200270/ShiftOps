from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shiftops_api.infra.db.base import Base
from shiftops_api.infra.db.mixins import TimestampMixin, UuidPkMixin


class Location(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "locations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    tg_admin_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    geo: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
