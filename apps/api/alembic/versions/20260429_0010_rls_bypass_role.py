"""NOLOGIN BYPASSRLS role for controlled RLS bypass (SET LOCAL ROLE).

PostgreSQL ``row_security = off`` does **not** skip policies for normal roles: it
makes statements that would touch RLS fail instead (pg_dump relies on this).

Under ``FORCE ROW LEVEL SECURITY`` the app must switch ``current_role`` to a
BYPASSRLS role for cross-tenant paths (auth, worker sweep, org bootstrap).

Revision ID: 0010_rls_bypass_role
Revises: 0009_shift_handover_summary
Create Date: 2026-04-29

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_rls_bypass_role"
down_revision: str | None = "0009_shift_handover_summary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $do$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'shiftops_rls_bypass') THEN
            CREATE ROLE shiftops_rls_bypass BYPASSRLS NOLOGIN;
          END IF;
        END
        $do$;
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO shiftops_rls_bypass")
    op.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO shiftops_rls_bypass")
    op.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO shiftops_rls_bypass")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO shiftops_rls_bypass"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO shiftops_rls_bypass"
    )


def downgrade() -> None:
    op.execute(
        """
        DO $do$
        DECLARE
          rec record;
        BEGIN
          FOR rec IN
            SELECT quote_ident(r.rolname) AS rn
            FROM pg_auth_members m
            JOIN pg_roles r ON r.oid = m.member
            WHERE m.roleid = (SELECT oid FROM pg_roles WHERE rolname = 'shiftops_rls_bypass')
          LOOP
            EXECUTE 'REVOKE shiftops_rls_bypass FROM ' || rec.rn;
          END LOOP;
        END
        $do$;
        """
    )
    op.execute("DROP ROLE IF EXISTS shiftops_rls_bypass")
