"""Add `section` column to template_tasks for grouped checklists.

Revision ID: 0006_template_section
Revises: 0005_invites_owner_sys
Create Date: 2026-04-29

The free-form "Кухня / Зал / Бар" headings the owner pastes via the bulk
import are stored on the task itself. Keeping this on the task (rather
than a parent table) avoids a join on the hot read path of
``GET /v1/shifts/me``: ordering by ``order_index`` already groups
identical sections together, so the renderer just walks the list once.

64 chars is generous for a HoReCa section name and short enough to
keep B-tree statistics tame if we ever index it.

We also reserve ``Template.default_schedule`` for the recurrence config
that ``CreateRecurringShiftsTickUseCase`` reads. The column already
exists (it was added in the initial schema), so this revision is a
schema-level no-op for that part — only ``section`` actually changes
the table structure.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_template_section"
down_revision: str | None = "0005_invites_owner_sys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "template_tasks",
        sa.Column("section", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("template_tasks", "section")
