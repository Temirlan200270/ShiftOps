from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shiftops_api.infra.db.base import Base
from shiftops_api.infra.db.mixins import TimestampMixin, UuidPkMixin


class Organization(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str] = mapped_column(String(32), nullable=False, default="free")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Recurring weekly windows + dated overrides (see ``BusinessHoursConfig``).
    business_hours: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, insert_default=dict
    )
