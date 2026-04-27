"""shifts.score_formula_version + indexes for operator history.

Revision ID: 0002_score_formula_version
Revises: 0001_initial
Create Date: 2026-04-27 07:30:00

Why two changes in one migration:
- ``score_formula_version`` needs to land before ``compute_score`` is wired
  to read it; otherwise running ``alembic upgrade`` on prod between two
  deploys briefly serves 500s.
- The history index is a one-line composite that the operator-history query
  (``apps/api/shiftops_api/api/v1/shifts.py: GET /v1/shifts/history``) sorts
  by. Better to ship them together than have two consecutive migrations.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_score_formula_version"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1 means the v1 formula. Existing rows are backfilled with 1 (which is
    # what they were *actually* scored with — the formula didn't change).
    op.add_column(
        "shifts",
        sa.Column(
            "score_formula_version",
            sa.SmallInteger(),
            nullable=False,
            server_default="1",
        ),
    )

    # Operator-history query: WHERE operator_user_id = :uid AND status IN
    # (closed_clean, closed_with_violations) ORDER BY scheduled_start DESC.
    # Without this index it's a seq scan once a single operator has 1k
    # shifts (a year of daily work).
    op.create_index(
        "ix_shifts_operator_history",
        "shifts",
        ["operator_user_id", "scheduled_start"],
        postgresql_using="btree",
    )


def downgrade() -> None:
    op.drop_index("ix_shifts_operator_history", table_name="shifts")
    op.drop_column("shifts", "score_formula_version")
