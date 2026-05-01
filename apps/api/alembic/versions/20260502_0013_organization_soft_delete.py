"""Soft-delete metadata for organizations (30-day retention before hard delete).

``deleted_at`` starts the grace window. :func:`purge_deleted_organizations_tick`
hard-deletes rows past retention using existing ``ON DELETE CASCADE`` chains.

Revision ID: 0013_organization_soft_delete
Revises: 0012_bypass_pooler_grants
Create Date: 2026-05-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_organization_soft_delete"
down_revision: str | None = "0012_bypass_pooler_grants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_organizations_deleted_at",
        "organizations",
        ["deleted_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_organizations_deleted_at", table_name="organizations")
    op.drop_column("organizations", "deleted_at")
