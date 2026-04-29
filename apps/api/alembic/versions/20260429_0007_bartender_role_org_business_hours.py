"""Add bartender role + organization.business_hours JSONB.

Revision ID: 0007_bartender_business_hours
Revises: 0006_template_section
Create Date: 2026-04-29

- Extends CHECK constraints on users.role, templates.role_target, invites.role.
- Adds organizations.business_hours for recurring weekly windows + dated
  one-off hours (validated in application code, not DB).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_bartender_business_hours"
down_revision: str | None = "0006_template_section"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "business_hours",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.drop_constraint("ck_users_role_allowed", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role_allowed",
        "users",
        "role IN ('owner','admin','operator','bartender')",
    )

    op.drop_constraint("ck_templates_role_target_allowed", "templates", type_="check")
    op.create_check_constraint(
        "ck_templates_role_target_allowed",
        "templates",
        "role_target IN ('owner','admin','operator','bartender')",
    )

    op.drop_constraint("ck_invites_role_invitable_only", "invites", type_="check")
    op.create_check_constraint(
        "ck_invites_role_invitable_only",
        "invites",
        "role IN ('owner','admin','operator','bartender')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_invites_role_invitable_only", "invites", type_="check")
    op.create_check_constraint(
        "ck_invites_role_invitable_only",
        "invites",
        "role IN ('owner','admin','operator')",
    )

    op.drop_constraint("ck_templates_role_target_allowed", "templates", type_="check")
    op.create_check_constraint(
        "ck_templates_role_target_allowed",
        "templates",
        "role_target IN ('owner','admin','operator')",
    )

    op.drop_constraint("ck_users_role_allowed", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role_allowed",
        "users",
        "role IN ('owner','admin','operator')",
    )

    op.drop_column("organizations", "business_hours")
