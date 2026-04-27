"""Apply RLS to table owners (FORCE ROW LEVEL SECURITY).

Revision ID: 0003_force_rls
Revises: 0002_score_formula_version
Create Date: 2026-04-28 00:00:00

Without FORCE, PostgreSQL lets the **table owner** (and superusers) bypass RLS
entirely. CI and production app users typically own the migrated tables, so
tenant policies were never enforced — integration tests and prod would see
cross-tenant rows unless a non-owner role was used.

`NO FORCE` in downgrade restores the default owner-bypass behaviour (only if
you ever need to revert; normally keep FORCE in production).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_force_rls"
down_revision: str | None = "0002_score_formula_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RLS_TABLES = (
    "locations",
    "users",
    "templates",
    "template_tasks",
    "shifts",
    "task_instances",
    "attachments",
    "audit_events",
)


def upgrade() -> None:
    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
