"""delay_reason on shifts; shift_swap_requests for peer swap.

Revision ID: 0016_delay_reason_swap
Revises: 0015_claim_slots_pool
Create Date: 2026-05-03

``revision`` id must stay ≤32 chars — ``alembic_version.version_num`` is VARCHAR(32).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_delay_reason_swap"
down_revision: str | None = "0015_claim_slots_pool"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("shifts", sa.Column("delay_reason", sa.Text(), nullable=True))

    op.create_table(
        "shift_swap_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "proposer_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "counterparty_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "proposer_shift_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shifts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "counterparty_shift_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shifts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("message", sa.String(280), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','accepted','declined','cancelled','expired')",
            name="ck_shift_swap_requests_status",
        ),
    )
    op.create_index(
        "ix_shift_swap_requests_org",
        "shift_swap_requests",
        ["organization_id"],
    )
    op.create_index(
        "ix_shift_swap_requests_counterparty_status",
        "shift_swap_requests",
        ["counterparty_user_id", "status"],
    )
    op.create_index(
        "ix_shift_swap_requests_proposer_status",
        "shift_swap_requests",
        ["proposer_user_id", "status"],
    )
    op.create_index(
        "ix_shift_swap_requests_proposer_shift",
        "shift_swap_requests",
        ["proposer_shift_id"],
    )

    op.execute(
        """
        CREATE UNIQUE INDEX uq_shift_swap_pending_proposer_shift
        ON shift_swap_requests (proposer_shift_id)
        WHERE status = 'pending';
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_shift_swap_pending_counterparty_shift
        ON shift_swap_requests (counterparty_shift_id)
        WHERE status = 'pending';
        """
    )

    op.execute("ALTER TABLE shift_swap_requests ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY shift_swap_requests_tenant_isolation ON shift_swap_requests
            USING (organization_id = current_setting('app.org_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.org_id', true)::uuid);
        """
    )
    op.execute("ALTER TABLE shift_swap_requests FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE shift_swap_requests NO FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "DROP POLICY IF EXISTS shift_swap_requests_tenant_isolation ON shift_swap_requests"
    )
    op.execute("ALTER TABLE shift_swap_requests DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS uq_shift_swap_pending_counterparty_shift")
    op.execute("DROP INDEX IF EXISTS uq_shift_swap_pending_proposer_shift")
    op.drop_table("shift_swap_requests")
    op.drop_column("shifts", "delay_reason")
