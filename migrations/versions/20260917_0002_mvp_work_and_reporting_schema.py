"""mvp work and reporting schema

Revision ID: 20260917_0002
Revises: 20260916_0001
Create Date: 2026-09-17 17:49:24.208477
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_0002"
down_revision: str | None = "20260916_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Fail before any DDL rather than renaming or deleting pre-existing organizations.
    if not op.get_context().as_sql:
        duplicate = (
            op.get_bind()
            .execute(
                sa.text("SELECT 1 FROM organizations GROUP BY parent_id, name HAVING COUNT(*) > 1")
            )
            .first()
        )
        if duplicate is not None:
            raise RuntimeError("Duplicate sibling organization names; resolve before migration")
    op.create_table(
        "projects",
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("next_ticket_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("history_complete_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "next_ticket_number > 0", name=op.f("ck_projects_positive_ticket_counter")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_projects_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint("key", name=op.f("uq_projects_key")),
    )
    op.create_table(
        "report_skills",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_report_skills_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_skills")),
        sa.UniqueConstraint("key", name=op.f("uq_report_skills_key")),
    )
    op.create_table(
        "project_members",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), server_default="PROJECT_USER", nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('PROJECT_ADMIN', 'PROJECT_USER')",
            name=op.f("ck_project_members_role_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_members_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_project_members_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_members")),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
    )
    with op.batch_alter_table("project_members", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_project_members_user_id"), ["user_id"], unique=False)

    op.create_table(
        "report_skill_versions",
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("instructions_markdown", sa.Text(), nullable=False),
        sa.Column("input_json_schema", sa.JSON(), nullable=False),
        sa.Column("output_json_schema", sa.JSON(), nullable=False),
        sa.Column("generation_defaults", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.CheckConstraint(
            "version > 0 AND schema_version > 0",
            name=op.f("ck_report_skill_versions_positive_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_report_skill_versions_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["report_skills.id"],
            name=op.f("fk_report_skill_versions_skill_id_report_skills"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_skill_versions")),
        sa.UniqueConstraint("skill_id", "version", name="uq_report_skill_versions_skill_version"),
    )
    op.create_table(
        "saved_filters",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("visibility", sa.String(length=16), server_default="PERSONAL", nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "visibility IN ('PERSONAL', 'PROJECT')",
            name=op.f("ck_saved_filters_visibility_allowed"),
        ),
        sa.CheckConstraint(
            "schema_version > 0", name=op.f("ck_saved_filters_positive_schema_version")
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_saved_filters_owner_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_saved_filters_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_filters")),
    )
    with op.batch_alter_table("saved_filters", schema=None) as batch_op:
        batch_op.create_index(
            "ix_saved_filters_scope", ["project_id", "visibility", "owner_id"], unique=False
        )

    op.create_table(
        "ticket_deletion_batches",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("root_ticket_key", sa.String(length=64), nullable=False),
        sa.Column("deleted_by_id", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restored_by_id", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.CheckConstraint(
            "purge_after >= deleted_at",
            name=op.f("ck_ticket_deletion_batches_purge_after_deletion"),
        ),
        sa.CheckConstraint(
            "restored_at IS NULL OR restored_at >= deleted_at",
            name=op.f("ck_ticket_deletion_batches_restore_after_deletion"),
        ),
        sa.CheckConstraint(
            "purged_at IS NULL OR (purged_at >= deleted_at AND restored_at IS NULL)",
            name=op.f("ck_ticket_deletion_batches_purge_not_restored"),
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by_id"],
            ["users.id"],
            name=op.f("fk_ticket_deletion_batches_deleted_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_ticket_deletion_batches_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["restored_by_id"],
            ["users.id"],
            name=op.f("fk_ticket_deletion_batches_restored_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_deletion_batches")),
        sa.UniqueConstraint("project_id", "id", name="uq_ticket_deletion_batches_project_id"),
    )
    with op.batch_alter_table("ticket_deletion_batches", schema=None) as batch_op:
        batch_op.create_index(
            "ix_ticket_deletion_batches_purge", ["restored_at", "purge_after"], unique=False
        )

    op.create_table(
        "report_runs",
        sa.Column("key", sa.String(length=36), nullable=False),
        sa.Column("requested_by_id", sa.Integer(), nullable=False),
        sa.Column("skill_version_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=100), server_default="Asia/Seoul", nullable=False),
        sa.Column("selection", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("input_schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("input_payload", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("input_sha256", sa.String(length=64), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name=op.f("ck_report_runs_status_allowed"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('RUNNING', 'SUCCEEDED') OR input_payload IS NOT NULL",
            name=op.f("ck_report_runs_execution_requires_input"),
        ),
        sa.CheckConstraint(
            "(input_payload IS NULL AND input_sha256 IS NULL AND captured_at IS NULL) OR "
            "(input_payload IS NOT NULL AND input_sha256 IS NOT NULL AND captured_at IS NOT NULL)",
            name=op.f("ck_report_runs_input_snapshot_complete"),
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at >= created_at",
            name=op.f("ck_report_runs_expiry_after_creation"),
        ),
        sa.CheckConstraint(
            "input_schema_version > 0", name=op.f("ck_report_runs_positive_schema_version")
        ),
        sa.CheckConstraint("period_start < period_end", name=op.f("ck_report_runs_valid_period")),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["users.id"],
            name=op.f("fk_report_runs_requested_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["skill_version_id"],
            ["report_skill_versions.id"],
            name=op.f("fk_report_runs_skill_version_id_report_skill_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_runs")),
        sa.UniqueConstraint("key", name=op.f("uq_report_runs_key")),
    )
    with op.batch_alter_table("report_runs", schema=None) as batch_op:
        batch_op.create_index(
            "ix_report_runs_requester_created", ["requested_by_id", "created_at"], unique=False
        )
        batch_op.create_index(
            "ix_report_runs_status_created", ["status", "created_at"], unique=False
        )

    op.create_table(
        "tickets",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=16), server_default="TASK", nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("body_schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=24), server_default="TODO", nullable=False),
        sa.Column("priority", sa.String(length=16), server_default="MAJOR", nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("creator_id", sa.Integer(), nullable=False),
        sa.Column("assignee_id", sa.Integer(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("planned_start_date", sa.Date(), nullable=True),
        sa.Column("planned_end_date", sa.Date(), nullable=True),
        sa.Column("actual_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress_percent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_milestone", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "sort_order", sa.Numeric(precision=20, scale=6), server_default="0", nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deletion_batch_id", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(type = 'EPIC' AND parent_id IS NULL) OR type = 'TASK' OR "
            "(type = 'SUBTASK' AND parent_id IS NOT NULL)",
            name=op.f("ck_tickets_parent_shape"),
        ),
        sa.CheckConstraint(
            "priority IN ('TRIVIAL', 'MINOR', 'MAJOR', 'CRITICAL', 'BLOCKER')",
            name=op.f("ck_tickets_priority_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('TODO', 'IN_PROGRESS', 'DONE', 'ON_HOLD', 'CANCELLED')",
            name=op.f("ck_tickets_status_allowed"),
        ),
        sa.CheckConstraint(
            "type IN ('EPIC', 'TASK', 'SUBTASK')", name=op.f("ck_tickets_type_allowed")
        ),
        sa.CheckConstraint(
            "(deleted_at IS NULL AND deletion_batch_id IS NULL) OR "
            "(deleted_at IS NOT NULL AND deletion_batch_id IS NOT NULL)",
            name=op.f("ck_tickets_deletion_pair"),
        ),
        sa.CheckConstraint(
            "body_schema_version > 0", name=op.f("ck_tickets_positive_body_version")
        ),
        sa.CheckConstraint(
            "number > 0 AND version > 0", name=op.f("ck_tickets_positive_number_version")
        ),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id != id", name=op.f("ck_tickets_not_own_parent")
        ),
        sa.CheckConstraint(
            "planned_start_date IS NULL OR planned_end_date IS NULL OR "
            "planned_start_date <= planned_end_date",
            name=op.f("ck_tickets_schedule_order"),
        ),
        sa.CheckConstraint(
            "progress_percent BETWEEN 0 AND 100", name=op.f("ck_tickets_progress_range")
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["users.id"],
            name=op.f("fk_tickets_assignee_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["users.id"],
            name=op.f("fk_tickets_creator_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "deletion_batch_id"],
            ["ticket_deletion_batches.project_id", "ticket_deletion_batches.id"],
            name="fk_tickets_project_deletion_batch",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "parent_id"],
            ["tickets.project_id", "tickets.id"],
            name="fk_tickets_project_parent",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_tickets_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tickets")),
        sa.UniqueConstraint("key", name=op.f("uq_tickets_key")),
        sa.UniqueConstraint("project_id", "id", name="uq_tickets_project_id"),
        sa.UniqueConstraint("project_id", "number", name="uq_tickets_project_number"),
    )
    with op.batch_alter_table("tickets", schema=None) as batch_op:
        batch_op.create_index(
            "ix_tickets_assignee_due", ["assignee_id", "deleted_at", "due_date"], unique=False
        )
        batch_op.create_index(
            "ix_tickets_creator_updated", ["creator_id", "deleted_at", "updated_at"], unique=False
        )
        batch_op.create_index(
            "ix_tickets_project_parent", ["project_id", "parent_id"], unique=False
        )
        batch_op.create_index(
            "ix_tickets_project_schedule",
            ["project_id", "planned_start_date", "planned_end_date"],
            unique=False,
        )
        batch_op.create_index(
            "ix_tickets_project_status", ["project_id", "deleted_at", "status"], unique=False
        )

    op.create_table(
        "comments",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("body_schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_id", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version > 0 AND body_schema_version > 0", name=op.f("ck_comments_positive_versions")
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_comments_author_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by_id"],
            ["users.id"],
            name=op.f("fk_comments_deleted_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "ticket_id"],
            ["tickets.project_id", "tickets.id"],
            name="fk_comments_ticket",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comments")),
        sa.UniqueConstraint("project_id", "ticket_id", "id", name="uq_comments_project_ticket_id"),
    )
    with op.batch_alter_table("comments", schema=None) as batch_op:
        batch_op.create_index(
            "ix_comments_ticket_created", ["ticket_id", "created_at", "id"], unique=False
        )

    op.create_table(
        "report_attempts",
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("runtime_profile", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("model_digest", sa.String(length=255), nullable=True),
        sa.Column("generation_parameters", sa.JSON(), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("response_metadata", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("output_schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("output_payload", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("output_markdown", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.CheckConstraint(
            "status != 'SUCCEEDED' OR (output_markdown IS NOT NULL AND "
            "output_payload IS NOT NULL AND response_text IS NOT NULL AND finished_at IS NOT NULL)",
            name=op.f("ck_report_attempts_success_requires_output"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name=op.f("ck_report_attempts_status_allowed"),
        ),
        sa.CheckConstraint(
            "(input_tokens IS NULL OR input_tokens >= 0) AND "
            "(output_tokens IS NULL OR output_tokens >= 0)",
            name=op.f("ck_report_attempts_nonnegative_tokens"),
        ),
        sa.CheckConstraint(
            "attempt_number > 0 AND output_schema_version > 0",
            name=op.f("ck_report_attempts_positive_versions"),
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name=op.f("ck_report_attempts_finish_after_start"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["report_runs.id"],
            name=op.f("fk_report_attempts_run_id_report_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_attempts")),
        sa.UniqueConstraint("run_id", "attempt_number", name="uq_report_attempts_run_number"),
    )
    op.create_table(
        "report_run_projects",
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_report_run_projects_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["report_runs.id"],
            name=op.f("fk_report_run_projects_run_id_report_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_run_projects")),
        sa.UniqueConstraint("run_id", "project_id", name="uq_report_run_projects_run_project"),
    )
    with op.batch_alter_table("report_run_projects", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_report_run_projects_project_id"), ["project_id"], unique=False
        )

    op.create_table(
        "ticket_history",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.String(length=36), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("ticket_version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("before_state", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("after_state", sa.JSON(), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.CheckConstraint(
            "event_type IN ('CREATED', 'UPDATED', 'STATUS_CHANGED', 'RELATION_CHANGED', "
            "'CONTENT_CHANGED', 'DELETED', 'RESTORED')",
            name=op.f("ck_ticket_history_event_type_allowed"),
        ),
        sa.CheckConstraint(
            "ticket_version > 0 AND schema_version > 0",
            name=op.f("ck_ticket_history_positive_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_ticket_history_actor_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "ticket_id"],
            ["tickets.project_id", "tickets.id"],
            name="fk_ticket_history_ticket",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_history")),
        sa.UniqueConstraint("event_key", name=op.f("uq_ticket_history_event_key")),
        sa.UniqueConstraint("ticket_id", "ticket_version", name="uq_ticket_history_ticket_version"),
    )
    with op.batch_alter_table("ticket_history", schema=None) as batch_op:
        batch_op.create_index("ix_ticket_history_operation", ["operation_id"], unique=False)
        batch_op.create_index(
            "ix_ticket_history_period", ["project_id", "occurred_at", "id"], unique=False
        )
        batch_op.create_index(
            "ix_ticket_history_ticket_time", ["ticket_id", "occurred_at", "id"], unique=False
        )

    op.create_table(
        "ticket_relations",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("source_ticket_id", sa.Integer(), nullable=False),
        sa.Column("target_ticket_id", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(length=24), nullable=False),
        sa.Column("dependency_kind", sa.String(length=2), nullable=True),
        sa.Column("lag_days", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.CheckConstraint(
            "(relation_type = 'RELATED' AND dependency_kind IS NULL AND lag_days = 0) OR "
            "(relation_type = 'DEPENDS_ON' AND dependency_kind IS NOT NULL AND "
            "dependency_kind IN ('FS', 'SS', 'FF', 'SF'))",
            name=op.f("ck_ticket_relations_dependency_shape"),
        ),
        sa.CheckConstraint(
            "relation_type != 'RELATED' OR source_ticket_id < target_ticket_id",
            name=op.f("ck_ticket_relations_canonical_related_order"),
        ),
        sa.CheckConstraint(
            "relation_type IN ('RELATED', 'DEPENDS_ON')",
            name=op.f("ck_ticket_relations_type_allowed"),
        ),
        sa.CheckConstraint(
            "source_ticket_id != target_ticket_id",
            name=op.f("ck_ticket_relations_different_endpoints"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_ticket_relations_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "source_ticket_id"],
            ["tickets.project_id", "tickets.id"],
            name="fk_ticket_relations_source",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "target_ticket_id"],
            ["tickets.project_id", "tickets.id"],
            name="fk_ticket_relations_target",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_relations")),
        sa.UniqueConstraint(
            "project_id",
            "source_ticket_id",
            "target_ticket_id",
            "relation_type",
            name="uq_ticket_relations_endpoints_type",
        ),
    )
    with op.batch_alter_table("ticket_relations", schema=None) as batch_op:
        batch_op.create_index(
            "ix_ticket_relations_target", ["project_id", "target_ticket_id"], unique=False
        )

    op.create_table(
        "attachments",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("comment_id", sa.Integer(), nullable=True),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_backend", sa.String(length=32), server_default="local", nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("uploaded_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_id", sa.Integer(), nullable=True),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.CheckConstraint(
            "(deleted_at IS NULL AND purge_after IS NULL) OR "
            "(deleted_at IS NOT NULL AND purge_after IS NOT NULL AND purge_after >= deleted_at)",
            name=op.f("ck_attachments_deletion_schedule"),
        ),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_attachments_nonnegative_size")),
        sa.ForeignKeyConstraint(
            ["deleted_by_id"],
            ["users.id"],
            name=op.f("fk_attachments_deleted_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "ticket_id", "comment_id"],
            ["comments.project_id", "comments.ticket_id", "comments.id"],
            name="fk_attachments_comment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "ticket_id"],
            ["tickets.project_id", "tickets.id"],
            name="fk_attachments_ticket",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
            name=op.f("fk_attachments_uploaded_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachments")),
        sa.UniqueConstraint("storage_backend", "storage_key", name="uq_attachments_storage_key"),
    )
    with op.batch_alter_table("attachments", schema=None) as batch_op:
        batch_op.create_index("ix_attachments_purge", ["purge_after"], unique=False)
        batch_op.create_index(
            "ix_attachments_ticket", ["project_id", "ticket_id", "deleted_at"], unique=False
        )

    op.create_table(
        "mentions",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("comment_id", sa.Integer(), nullable=True),
        sa.Column("target_user_id", sa.Integer(), nullable=False),
        sa.Column("mentioned_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["mentioned_by_id"],
            ["users.id"],
            name=op.f("fk_mentions_mentioned_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "ticket_id", "comment_id"],
            ["comments.project_id", "comments.ticket_id", "comments.id"],
            name="fk_mentions_comment",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "ticket_id"],
            ["tickets.project_id", "tickets.id"],
            name="fk_mentions_ticket",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name=op.f("fk_mentions_target_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mentions")),
        sa.UniqueConstraint("comment_id", "target_user_id", name="uq_mentions_comment_user"),
    )
    with op.batch_alter_table("mentions", schema=None) as batch_op:
        batch_op.create_index(
            "ix_mentions_inbox",
            ["target_user_id", "removed_at", "read_at", "created_at"],
            unique=False,
        )
        batch_op.create_index(
            "uq_mentions_description_user",
            ["ticket_id", "target_user_id"],
            unique=True,
            sqlite_where=sa.text("comment_id IS NULL"),
            postgresql_where=sa.text("comment_id IS NULL"),
        )

    with op.batch_alter_table("organizations", schema=None) as batch_op:
        batch_op.create_index(
            "uq_organizations_root_name",
            ["name"],
            unique=True,
            sqlite_where=sa.text("parent_id IS NULL"),
            postgresql_where=sa.text("parent_id IS NULL"),
        )
        batch_op.create_index("uq_organizations_sibling_name", ["parent_id", "name"], unique=True)

    # ### end Alembic commands ###


def downgrade() -> None:
    # Destructive: restore a backup to recover work/report data after downgrading.
    with op.batch_alter_table("organizations", schema=None) as batch_op:
        batch_op.drop_index("uq_organizations_sibling_name")
        batch_op.drop_index(
            "uq_organizations_root_name",
            sqlite_where=sa.text("parent_id IS NULL"),
            postgresql_where=sa.text("parent_id IS NULL"),
        )

    with op.batch_alter_table("mentions", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_mentions_description_user",
            sqlite_where=sa.text("comment_id IS NULL"),
            postgresql_where=sa.text("comment_id IS NULL"),
        )
        batch_op.drop_index("ix_mentions_inbox")

    op.drop_table("mentions")
    with op.batch_alter_table("attachments", schema=None) as batch_op:
        batch_op.drop_index("ix_attachments_ticket")
        batch_op.drop_index("ix_attachments_purge")

    op.drop_table("attachments")
    with op.batch_alter_table("ticket_relations", schema=None) as batch_op:
        batch_op.drop_index("ix_ticket_relations_target")

    op.drop_table("ticket_relations")
    with op.batch_alter_table("ticket_history", schema=None) as batch_op:
        batch_op.drop_index("ix_ticket_history_ticket_time")
        batch_op.drop_index("ix_ticket_history_period")
        batch_op.drop_index("ix_ticket_history_operation")

    op.drop_table("ticket_history")
    with op.batch_alter_table("report_run_projects", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_report_run_projects_project_id"))

    op.drop_table("report_run_projects")
    op.drop_table("report_attempts")
    with op.batch_alter_table("comments", schema=None) as batch_op:
        batch_op.drop_index("ix_comments_ticket_created")

    op.drop_table("comments")
    with op.batch_alter_table("tickets", schema=None) as batch_op:
        batch_op.drop_index("ix_tickets_project_status")
        batch_op.drop_index("ix_tickets_project_schedule")
        batch_op.drop_index("ix_tickets_project_parent")
        batch_op.drop_index("ix_tickets_creator_updated")
        batch_op.drop_index("ix_tickets_assignee_due")

    # SQLite checks self-referencing RESTRICT FKs even while dropping a populated table.
    # Its dependent tables have already been removed; detach the disposable hierarchy.
    op.execute("UPDATE tickets SET parent_id = NULL, type = 'TASK'")
    op.drop_table("tickets")
    with op.batch_alter_table("report_runs", schema=None) as batch_op:
        batch_op.drop_index("ix_report_runs_status_created")
        batch_op.drop_index("ix_report_runs_requester_created")

    op.drop_table("report_runs")
    with op.batch_alter_table("ticket_deletion_batches", schema=None) as batch_op:
        batch_op.drop_index("ix_ticket_deletion_batches_purge")

    op.drop_table("ticket_deletion_batches")
    with op.batch_alter_table("saved_filters", schema=None) as batch_op:
        batch_op.drop_index("ix_saved_filters_scope")

    op.drop_table("saved_filters")
    op.drop_table("report_skill_versions")
    with op.batch_alter_table("project_members", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_project_members_user_id"))

    op.drop_table("project_members")
    op.drop_table("report_skills")
    op.drop_table("projects")
    # ### end Alembic commands ###
