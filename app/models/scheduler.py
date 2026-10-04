"""Cron scheduler의 작업 정의와 실행 이력 모델."""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TimestampMixin
from app.db.types import UTCDateTime, utc_now


class ScheduledJob(IntegerPrimaryKeyMixin, TimestampMixin, Base):
    """DB에 보관하는 단일 cron 작업 설정."""

    __tablename__ = "scheduled_jobs"
    __table_args__ = (
        CheckConstraint("length(job_key) > 0", name="job_key_nonempty"),
        CheckConstraint("length(cron_expression) > 0", name="cron_expression_nonempty"),
    )

    job_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    cron_expression: Mapped[str] = mapped_column(String(100), nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(64), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )


class ScheduledJobRun(IntegerPrimaryKeyMixin, Base):
    """실행 시각 계산과 분리된 작업 실행 결과."""

    __tablename__ = "scheduled_job_runs"
    __table_args__ = (
        CheckConstraint(
            "trigger_source IN ('CRON', 'MANUAL')", name="trigger_source_allowed"
        ),
        CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED')", name="status_allowed"
        ),
        Index("ix_scheduled_job_runs_job_started", "scheduled_job_id", "started_at"),
    )

    scheduled_job_id: Mapped[int] = mapped_column(
        ForeignKey("scheduled_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    trigger_source: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    result_code: Mapped[str | None] = mapped_column(String(64))
