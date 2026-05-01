"""Grant shiftops_rls_bypass to Supabase-style pooler login roles.

``0011`` grants membership only to ``session_user`` during ``alembic upgrade``.
If ``ALEMBIC_DATABASE_URL`` (or a one-off DSN) connects as a different Postgres
role than ``DATABASE_URL`` (async runtime on the transaction pooler), the API
user never receives ``GRANT shiftops_rls_bypass`` and ``SET LOCAL ROLE`` fails.

Supabase pooler URIs almost always use a LOGIN role named ``postgres`` or
``postgres.<project_ref>``. This revision grants bypass membership to every such
role that exists, idempotently.

Revision ID: 0012_grant_rls_bypass_pooler_roles
Revises: 0011_grant_rls_bypass_membership
Create Date: 2026-05-02

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012_grant_rls_bypass_pooler_roles"
down_revision: str | None = "0011_grant_rls_bypass_membership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE_SQL = """
DO $do$
DECLARE
  r record;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'shiftops_rls_bypass') THEN
    RAISE NOTICE 'shiftops_rls_bypass missing — run migration 0010 first';
    RETURN;
  END IF;
  FOR r IN
    SELECT rolname
    FROM pg_roles
    WHERE rolcanlogin
      AND rolname IS DISTINCT FROM 'shiftops_rls_bypass'
      AND (rolname = 'postgres' OR rolname LIKE 'postgres.%')
  LOOP
    IF NOT EXISTS (
      SELECT 1
      FROM pg_auth_members m
      JOIN pg_roles member ON member.oid = m.member
      JOIN pg_roles granted ON granted.oid = m.roleid
      WHERE granted.rolname = 'shiftops_rls_bypass'
        AND member.rolname = r.rolname
    ) THEN
      EXECUTE format('GRANT shiftops_rls_bypass TO %I', r.rolname);
    END IF;
  END LOOP;
END
$do$;
"""

_DOWNGRADE_SQL = """
DO $do$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT rolname
    FROM pg_roles
    WHERE rolcanlogin
      AND rolname IS DISTINCT FROM 'shiftops_rls_bypass'
      AND (rolname = 'postgres' OR rolname LIKE 'postgres.%')
  LOOP
    IF EXISTS (
      SELECT 1
      FROM pg_auth_members m
      JOIN pg_roles member ON member.oid = m.member
      JOIN pg_roles granted ON granted.oid = m.roleid
      WHERE granted.rolname = 'shiftops_rls_bypass'
        AND member.rolname = r.rolname
    ) THEN
      EXECUTE format('REVOKE shiftops_rls_bypass FROM %I', r.rolname);
    END IF;
  END LOOP;
END
$do$;
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)
