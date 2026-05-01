"""Claim model: template slots, nullable shift assignee, station labels.

Revision ID: 0015_claim_slots_and_unassigned_pool
Revises: 0014_users_job_title
Create Date: 2026-05-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_claim_slots_and_unassigned_pool"
down_revision: str | None = "0014_users_job_title"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "templates",
        sa.Column("slot_count", sa.SmallInteger(), nullable=False, server_default="1"),
    )
    op.add_column(
        "templates",
        sa.Column(
            "unassigned_pool",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_check_constraint(
        "ck_templates_slot_count_positive",
        "templates",
        "slot_count >= 1",
    )

    op.add_column(
        "shifts",
        sa.Column(
            "slot_index",
            sa.SmallInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "shifts",
        sa.Column("station_label", sa.String(length=64), nullable=True),
    )
    op.alter_column(
        "shifts",
        "operator_user_id",
        existing_type=sa.UUID(),
        nullable=True,
    )

    op.create_index(
        "ix_shifts_org_scheduled_unassigned",
        "shifts",
        ["organization_id"],
        postgresql_where=sa.text(
            "status = 'scheduled' AND operator_user_id IS NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_shifts_org_scheduled_unassigned",
        table_name="shifts",
        postgresql_where=sa.text(
            "status = 'scheduled' AND operator_user_id IS NULL"
        ),
    )

    op.alter_column(
        "shifts",
        "operator_user_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
    op.drop_column("shifts", "station_label")
    op.drop_column("shifts", "slot_index")

    op.drop_constraint("ck_templates_slot_count_positive", "templates", type_="check")
    op.drop_column("templates", "unassigned_pool")
    op.drop_column("templates", "slot_count")
