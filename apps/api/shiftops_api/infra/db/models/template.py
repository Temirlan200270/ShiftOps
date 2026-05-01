from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, Enum as SAEnum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shiftops_api.domain.enums import UserRole
from shiftops_api.infra.db.base import Base
from shiftops_api.infra.db.mixins import TimestampMixin, UuidPkMixin


class Template(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "templates"
    __table_args__ = (
        CheckConstraint(
            "role_target IN ('owner','admin','operator','bartender')",
            name="ck_templates_role_target_allowed",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    role_target: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, native_enum=False, validate_strings=True),
        nullable=False,
        default=UserRole.OPERATOR,
    )
    default_schedule: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
