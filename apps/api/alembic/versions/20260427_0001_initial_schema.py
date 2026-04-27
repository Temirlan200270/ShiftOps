"""initial schema — organizations, locations, users, telegram_accounts,
templates, template_tasks, shifts, task_instances, attachments, audit_events.
Includes RLS policies and append-only trigger on audit_events.

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-27 00:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Tables that need RLS isolation by app.org_id (direct column on the row).
# task_instances / attachments have no organization_id — policies are defined
# below via shifts (and task_instances) joins.
RLS_TABLES = (
    "locations",
    "users",
    "templates",
    "template_tasks",
    "shifts",
    "audit_events",
)


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("plan", sa.String(32), nullable=False, server_default="free"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "locations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("tg_admin_chat_id", sa.BigInteger),
        sa.Column("geo", postgresql.JSONB),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_locations_organization_id", "locations", ["organization_id"])

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("locale", sa.String(8), nullable=False, server_default="ru"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("role IN ('owner','admin','operator')", name="ck_users_role_allowed"),
    )
    op.create_index("ix_users_organization_id", "users", ["organization_id"])
    op.create_index("ix_users_org_role", "users", ["organization_id", "role"])

    op.create_table(
        "telegram_accounts",
        sa.Column("tg_user_id", sa.BigInteger, primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tg_username", sa.String(64)),
        sa.Column("tg_language_code", sa.String(8)),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_telegram_accounts_user_id", "telegram_accounts", ["user_id"])

    op.create_table(
        "templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("role_target", sa.String(16), nullable=False, server_default="operator"),
        sa.Column("default_schedule", postgresql.JSONB),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "role_target IN ('owner','admin','operator')",
            name="ck_templates_role_target_allowed",
        ),
    )
    op.create_index("ix_templates_organization_id", "templates", ["organization_id"])

    op.create_table(
        "template_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("criticality", sa.String(16), nullable=False, server_default="required"),
        sa.Column("requires_photo", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("requires_comment", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
        sa.CheckConstraint(
            "criticality IN ('critical','required','optional')",
            name="ck_template_tasks_criticality_allowed",
        ),
    )
    op.create_index("ix_template_tasks_template_id", "template_tasks", ["template_id"])

    op.create_table(
        "shifts",
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
            sa.ForeignKey("locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "operator_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_start", sa.DateTime(timezone=True)),
        sa.Column("actual_end", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False, server_default="scheduled"),
        sa.Column("score", sa.Numeric(5, 2)),
        sa.Column("close_notes", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('scheduled','active','closed_clean','closed_with_violations','aborted')",
            name="ck_shifts_status_allowed",
        ),
    )
    op.create_index("ix_shifts_organization_id", "shifts", ["organization_id"])
    op.create_index("ix_shifts_location_id", "shifts", ["location_id"])
    op.create_index("ix_shifts_operator_user_id", "shifts", ["operator_user_id"])
    op.create_index(
        "ix_shifts_org_status_start",
        "shifts",
        ["organization_id", "status", "scheduled_start"],
    )

    op.create_table(
        "task_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "shift_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shifts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "template_task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("template_tasks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("waiver_reason", sa.String(64)),
        sa.Column("waiver_description", sa.Text),
        sa.Column(
            "waiver_decided_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("waiver_decided_at", sa.DateTime(timezone=True)),
        sa.Column("comment", sa.Text),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('pending','done','skipped','waived','waiver_pending','waiver_rejected')",
            name="ck_task_instances_status_allowed",
        ),
    )
    op.create_index("ix_task_instances_shift_id", "task_instances", ["shift_id"])
    op.create_index(
        "ix_task_instances_shift_status",
        "task_instances",
        ["shift_id", "status"],
    )

    op.create_table(
        "attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_instance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("storage_provider", sa.String(16), nullable=False, server_default="telegram"),
        sa.Column("tg_file_id", sa.String(255)),
        sa.Column("tg_file_unique_id", sa.String(64)),
        sa.Column("tg_archive_chat_id", sa.BigInteger),
        sa.Column("tg_archive_message_id", sa.BigInteger),
        sa.Column("r2_object_key", sa.String(512)),
        sa.Column("mime", sa.String(64), nullable=False, server_default="image/jpeg"),
        sa.Column("size_bytes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("phash", sa.String(32)),
        sa.Column("suspicious", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("capture_method", sa.String(16), nullable=False, server_default="camera"),
        sa.Column("geo", postgresql.JSONB),
        sa.Column("captured_at_server", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "storage_provider IN ('telegram','r2')",
            name="ck_attachments_storage_provider_allowed",
        ),
        sa.CheckConstraint(
            "capture_method IN ('camera','fallback','unknown')",
            name="ck_attachments_capture_method_allowed",
        ),
    )
    op.create_index(
        "ix_attachments_task_instance_id",
        "attachments",
        ["task_instance_id"],
    )
    op.create_index(
        "ix_attachments_task_captured",
        "attachments",
        ["task_instance_id", "captured_at_server"],
    )
    op.execute(
        "CREATE INDEX ix_attachments_suspicious "
        "ON attachments (task_instance_id) WHERE suspicious = true"
    )

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_audit_events_organization_id", "audit_events", ["organization_id"])
    op.create_index(
        "ix_audit_events_org_created",
        "audit_events",
        ["organization_id", "created_at"],
    )

    # ---- Append-only trigger on audit_events --------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_events_append_only()
            RETURNS trigger
            LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only (operation %)', TG_OP;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_no_update
            BEFORE UPDATE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION audit_events_append_only();
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_no_delete
            BEFORE DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION audit_events_append_only();
        """
    )

    # ---- Row-Level Security -------------------------------------------------
    # The pattern: enable RLS, force it (so even table owners are subject), and
    # add a single policy that permits rows where organization_id matches the
    # session GUC. The app sets `app.org_id` per transaction (e.g. set_config)
    # request transaction.
    for table in RLS_TABLES:
        if table == "template_tasks":
            # template_tasks has no org_id; isolation is via FK to templates.
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(
                f"""
                CREATE POLICY {table}_tenant_isolation ON {table}
                    USING (
                        EXISTS (
                            SELECT 1 FROM templates t
                             WHERE t.id = {table}.template_id
                               AND t.organization_id = current_setting('app.org_id', true)::uuid
                        )
                    )
                    WITH CHECK (
                        EXISTS (
                            SELECT 1 FROM templates t
                             WHERE t.id = {table}.template_id
                               AND t.organization_id = current_setting('app.org_id', true)::uuid
                        )
                    );
                """
            )
        else:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(
                f"""
                CREATE POLICY {table}_tenant_isolation ON {table}
                    USING (organization_id = current_setting('app.org_id', true)::uuid)
                    WITH CHECK (organization_id = current_setting('app.org_id', true)::uuid);
                """
            )

    # task_instances is isolated transitively via shift -> location -> org.
    op.execute("ALTER TABLE task_instances ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY task_instances_tenant_isolation ON task_instances
            USING (
                EXISTS (
                    SELECT 1 FROM shifts s
                     WHERE s.id = task_instances.shift_id
                       AND s.organization_id = current_setting('app.org_id', true)::uuid
                )
            )
            WITH CHECK (
                EXISTS (
                    SELECT 1 FROM shifts s
                     WHERE s.id = task_instances.shift_id
                       AND s.organization_id = current_setting('app.org_id', true)::uuid
                )
            );
        """
    )

    op.execute("ALTER TABLE attachments ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY attachments_tenant_isolation ON attachments
            USING (
                EXISTS (
                    SELECT 1 FROM task_instances ti
                      JOIN shifts s ON s.id = ti.shift_id
                     WHERE ti.id = attachments.task_instance_id
                       AND s.organization_id = current_setting('app.org_id', true)::uuid
                )
            )
            WITH CHECK (
                EXISTS (
                    SELECT 1 FROM task_instances ti
                      JOIN shifts s ON s.id = ti.shift_id
                     WHERE ti.id = attachments.task_instance_id
                       AND s.organization_id = current_setting('app.org_id', true)::uuid
                )
            );
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_update ON audit_events")
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_delete ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_events_append_only()")

    op.drop_table("audit_events")
    op.drop_table("attachments")
    op.drop_table("task_instances")
    op.drop_table("shifts")
    op.drop_table("template_tasks")
    op.drop_table("templates")
    op.drop_table("telegram_accounts")
    op.drop_table("users")
    op.drop_table("locations")
    op.drop_table("organizations")
