"""Add cron schedule definitions and execution records without registering jobs."""

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "20261005_0009"
down_revision = "20261004_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기존 데이터를 보존하며 빈 scheduler 테이블을 생성한다."""
    op.create_table(
        "scheduled_jobs",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("job_key", sa.String(length=100), nullable=False),
        sa.Column("cron_expression", sa.String(length=100), nullable=False),
        sa.Column("timezone_name", sa.String(length=64), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", UTCDateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", UTCDateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("length(job_key) > 0", name=op.f("ck_scheduled_jobs_job_key_nonempty")),
        sa.CheckConstraint(
            "length(cron_expression) > 0",
            name=op.f("ck_scheduled_jobs_cron_expression_nonempty"),
        ),
        sa.UniqueConstraint("job_key", name=op.f("uq_scheduled_jobs_job_key")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduled_jobs")),
    )
    op.create_table(
        "scheduled_job_runs",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("scheduled_job_id", sa.Integer(), nullable=False),
        sa.Column("trigger_source", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", UTCDateTime(), nullable=False),
        sa.Column("finished_at", UTCDateTime(), nullable=True),
        sa.Column("result_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "trigger_source IN ('CRON', 'MANUAL')",
            name=op.f("ck_scheduled_job_runs_trigger_source_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED')",
            name=op.f("ck_scheduled_job_runs_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["scheduled_job_id"],
            ["scheduled_jobs.id"],
            name=op.f("fk_scheduled_job_runs_scheduled_job_id_scheduled_jobs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduled_job_runs")),
    )
    op.create_index(
        "ix_scheduled_job_runs_job_started",
        "scheduled_job_runs",
        ["scheduled_job_id", "started_at"],
    )


def downgrade() -> None:
    """Scheduler 실행 이력과 작업 정의를 제거한다."""
    op.drop_index("ix_scheduled_job_runs_job_started", table_name="scheduled_job_runs")
    op.drop_table("scheduled_job_runs")
    op.drop_table("scheduled_jobs")
