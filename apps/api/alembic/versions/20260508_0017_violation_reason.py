"""violation_reason on shifts.

Revision ID: 0017_violation_reason
Revises: 0016_delay_reason_swap
Create Date: 2026-05-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_violation_reason"
down_revision: str | None = "0016_delay_reason_swap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("shifts", sa.Column("violation_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("shifts", "violation_reason")
