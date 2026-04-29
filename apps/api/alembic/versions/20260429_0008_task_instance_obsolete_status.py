"""Add `obsolete` status to task_instances for template drift.

Revision ID: 0008_task_instance_obsolete
Revises: 0007_bartender_role_org_business_hours
Create Date: 2026-04-29

We never hard-delete TaskInstance rows while a shift is running. When an admin
updates a template, tasks removed from the template are marked `obsolete` on
active/scheduled shifts so the checklist adapts without breaking progress.

Obsolete tasks are:
- hidden from `/v1/shifts/me`;
- excluded from close-time blocking/scoring;
- deleted on shift close (safe cleanup) so old template tasks can eventually be
  removed when no longer referenced.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_task_instance_obsolete"
down_revision: str | None = "0007_bartender_business_hours"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Replace CHECK constraint with a superset including 'obsolete'.
    #
    # Constraint names can differ between environments (e.g. if the initial
    # schema was created via SQLAlchemy autogen), so we locate the existing
    # check by definition and drop it dynamically.
    bind = op.get_bind()
    existing = bind.execute(
        sa.text(
            """
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'task_instances'
              AND c.contype = 'c'
              AND pg_get_constraintdef(c.oid) LIKE '%status%'
            """
        )
    ).fetchall()
    for (name,) in existing:
        op.execute(sa.text(f'ALTER TABLE task_instances DROP CONSTRAINT IF EXISTS "{name}"'))

    op.create_check_constraint(
        "status_allowed",
        "task_instances",
        "status IN ('pending','done','skipped','waived','waiver_pending','waiver_rejected','obsolete')",
    )


def downgrade() -> None:
    bind = op.get_bind()
    existing = bind.execute(
        sa.text(
            """
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'task_instances'
              AND c.contype = 'c'
              AND pg_get_constraintdef(c.oid) LIKE '%status%'
            """
        )
    ).fetchall()
    for (name,) in existing:
        op.execute(sa.text(f'ALTER TABLE task_instances DROP CONSTRAINT IF EXISTS "{name}"'))

    op.create_check_constraint(
        "status_allowed",
        "task_instances",
        "status IN ('pending','done','skipped','waived','waiver_pending','waiver_rejected')",
    )

