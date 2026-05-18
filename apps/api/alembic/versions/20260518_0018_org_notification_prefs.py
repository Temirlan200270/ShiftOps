"""org_notification_prefs — per-org configurable alert settings.

Revision ID: 0018_org_notification_prefs
Revises: 0017_violation_reason
Create Date: 2026-05-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0018_org_notification_prefs"
down_revision: str = "0017_violation_reason"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "notification_prefs",
            JSONB,
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "notification_prefs")
