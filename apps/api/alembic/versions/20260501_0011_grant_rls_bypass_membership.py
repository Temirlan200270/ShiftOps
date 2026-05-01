"""Grant shiftops_rls_bypass membership to the migration session role.

``SET LOCAL ROLE shiftops_rls_bypass`` requires the runtime DB user to be a
member of that NOLOGIN role. Migration ``0010`` creates the role but does not
grant membership to the application user; CI adds ``GRANT`` only for
``shiftops_app``. Supabase/Fly typically run Alembic and the API as the same
pooler user — this revision grants membership to ``session_user`` during
``upgrade()`` so production works without a manual SQL step.

Revision ID: 0011_grant_rls_bypass_membership
Revises: 0010_rls_bypass_role
Create Date: 2026-05-01

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011_grant_rls_bypass_membership"
down_revision: str | None = "0010_rls_bypass_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $do$
        DECLARE
          sess text := session_user;
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'shiftops_rls_bypass') THEN
            IF NOT EXISTS (
              SELECT 1
              FROM pg_auth_members m
              JOIN pg_roles member ON member.oid = m.member
              JOIN pg_roles granted ON granted.oid = m.roleid
              WHERE granted.rolname = 'shiftops_rls_bypass'
                AND member.rolname = sess
            ) THEN
              EXECUTE format('GRANT shiftops_rls_bypass TO %I', sess);
            END IF;
          END IF;
        END
        $do$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $do$
        DECLARE
          sess text := session_user;
        BEGIN
          IF EXISTS (
              SELECT 1
              FROM pg_auth_members m
              JOIN pg_roles member ON member.oid = m.member
              JOIN pg_roles granted ON granted.oid = m.roleid
              WHERE granted.rolname = 'shiftops_rls_bypass'
                AND member.rolname = sess
          ) THEN
            EXECUTE format('REVOKE shiftops_rls_bypass FROM %I', sess);
          END IF;
        END
        $do$;
        """
    )
