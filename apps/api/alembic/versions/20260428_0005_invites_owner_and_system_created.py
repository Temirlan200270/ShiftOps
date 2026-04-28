"""Allow owner invites + system-created invites.

Revision ID: 0005_invites_owner_and_system_created
Revises: 0004_invites
Create Date: 2026-04-28

We extend `invites.role` to include `owner` so the super-admin bot can onboard
the first owner into an organization without needing a Telegram ID at org
creation time.

We also allow `created_by` to be NULL so the platform (super-admin) can issue
an invite before any user exists in the tenant.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_invites_owner_and_system_created"
down_revision: str | None = "0004_invites"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # created_by: nullable for system-issued invites
    op.alter_column("invites", "created_by", existing_type=sa.UUID(), nullable=True)

    # role constraint: allow owner too
    op.drop_constraint("ck_invites_role_invitable_only", "invites", type_="check")
    op.create_check_constraint(
        "ck_invites_role_invitable_only",
        "invites",
        "role IN ('owner','admin','operator')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_invites_role_invitable_only", "invites", type_="check")
    op.create_check_constraint(
        "ck_invites_role_invitable_only",
        "invites",
        "role IN ('admin','operator')",
    )
    op.alter_column("invites", "created_by", existing_type=sa.UUID(), nullable=False)

