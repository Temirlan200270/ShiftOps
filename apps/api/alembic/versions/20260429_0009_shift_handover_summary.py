"""Add `handover_summary` to shifts.

Revision ID: 0009_shift_handover_summary
Revises: 0008_task_instance_obsolete
Create Date: 2026-04-29

Stores a short close-time summary that can be:
- posted to Telegram admin/owner chats (handover);
- displayed in the Web App history.

This keeps the summary stable for audit: closed shifts are not recomputed
from mutable templates.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_shift_handover_summary"
down_revision: str | None = "0008_task_instance_obsolete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("shifts", sa.Column("handover_summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("shifts", "handover_summary")

