"""Optional display job title for team members (UI label only; RBAC stays on role).

Revision ID: 0014_users_job_title
Revises: 0013_organization_soft_delete
Create Date: 2026-05-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_users_job_title"
down_revision: str | None = "0013_organization_soft_delete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("job_title", sa.String(length=80), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "job_title")
