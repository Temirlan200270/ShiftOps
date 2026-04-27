"""invites table for Telegram deep-link onboarding (owner/admin -> staff).

Revision ID: 0004_invites
Revises: 0003_force_rls
Create Date: 2026-04-29 00:00:00

Redeem path uses ``SET LOCAL row_security = off`` in the application (same
pattern as :class:`ExchangeInitDataUseCase`), not a SECURITY DEFINER function.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_invites"
down_revision: str | None = "0003_force_rls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("token", sa.String(128), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "used_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "role IN ('admin','operator')",
            name="ck_invites_role_invitable_only",
        ),
    )
    op.create_index("ix_invites_org_created", "invites", ["organization_id", "created_at"])
    op.create_index("ix_invites_token", "invites", ["token"], unique=True)

    op.execute("ALTER TABLE invites ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY invites_tenant_isolation ON invites
            USING (organization_id = current_setting('app.org_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.org_id', true)::uuid);
        """
    )
    op.execute("ALTER TABLE invites FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE invites NO FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS invites_tenant_isolation ON invites")
    op.execute("ALTER TABLE invites DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_invites_token", table_name="invites")
    op.drop_index("ix_invites_org_created", table_name="invites")
    op.drop_table("invites")
