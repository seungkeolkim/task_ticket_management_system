"""Versioned report instructions and reproducible local LLM request/response records.

No execution, network access, or permission bypass is provided by these models.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TimestampMixin
from app.db.types import UTCDateTime, utc_now
from app.domain.codes import RunStatus
from app.models.work import allowed


class ReportSkill(IntegerPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "report_skills"

    key: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class ReportSkillVersion(IntegerPrimaryKeyMixin, Base):
    __tablename__ = "report_skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_id", "version", name="uq_report_skill_versions_skill_version"),
        CheckConstraint("version > 0 AND schema_version > 0", name="positive_versions"),
    )

    skill_id: Mapped[int] = mapped_column(ForeignKey("report_skills.id", ondelete="RESTRICT"))
    version: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    instructions_markdown: Mapped[str] = mapped_column(Text)
    input_json_schema: Mapped[dict[str, Any]] = mapped_column(JSON)
    output_json_schema: Mapped[dict[str, Any]] = mapped_column(JSON)
    generation_defaults: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ReportRun(IntegerPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "report_runs"
    __table_args__ = (
        allowed("status", RunStatus, "status_allowed"),
        CheckConstraint("period_start < period_end", name="valid_period"),
        CheckConstraint("input_schema_version > 0", name="positive_schema_version"),
        CheckConstraint(
            "(input_payload IS NULL AND input_sha256 IS NULL AND captured_at IS NULL) OR "
            "(input_payload IS NOT NULL AND input_sha256 IS NOT NULL AND captured_at IS NOT NULL)",
            name="input_snapshot_complete",
        ),
        CheckConstraint(
            "status NOT IN ('RUNNING', 'SUCCEEDED') OR input_payload IS NOT NULL",
            name="execution_requires_input",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at >= created_at", name="expiry_after_creation"
        ),
        Index("ix_report_runs_requester_created", "requested_by_id", "created_at"),
        Index("ix_report_runs_status_created", "status", "created_at"),
    )

    key: Mapped[str] = mapped_column(String(36), unique=True)
    requested_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    skill_version_id: Mapped[int] = mapped_column(
        ForeignKey("report_skill_versions.id", ondelete="RESTRICT")
    )
    title: Mapped[str] = mapped_column(String(200))
    period_start: Mapped[datetime] = mapped_column(UTCDateTime())
    period_end: Mapped[datetime] = mapped_column(UTCDateTime())
    timezone: Mapped[str] = mapped_column(
        String(100), default="Asia/Seoul", server_default="Asia/Seoul"
    )
    selection: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", server_default="PENDING")
    input_schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    input_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    input_sha256: Mapped[str | None] = mapped_column(String(64))
    captured_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ReportRunProject(IntegerPrimaryKeyMixin, Base):
    __tablename__ = "report_run_projects"
    __table_args__ = (
        UniqueConstraint("run_id", "project_id", name="uq_report_run_projects_run_project"),
    )

    run_id: Mapped[int] = mapped_column(ForeignKey("report_runs.id", ondelete="CASCADE"))
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), index=True
    )


class ReportAttempt(IntegerPrimaryKeyMixin, Base):
    __tablename__ = "report_attempts"
    __table_args__ = (
        UniqueConstraint("run_id", "attempt_number", name="uq_report_attempts_run_number"),
        allowed("status", RunStatus, "status_allowed"),
        CheckConstraint(
            "attempt_number > 0 AND output_schema_version > 0", name="positive_versions"
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at", name="finish_after_start"
        ),
        CheckConstraint(
            "status != 'SUCCEEDED' OR (output_markdown IS NOT NULL AND "
            "output_payload IS NOT NULL AND response_text IS NOT NULL AND finished_at IS NOT NULL)",
            name="success_requires_output",
        ),
        CheckConstraint(
            "(input_tokens IS NULL OR input_tokens >= 0) AND "
            "(output_tokens IS NULL OR output_tokens >= 0)",
            name="nonnegative_tokens",
        ),
    )

    run_id: Mapped[int] = mapped_column(ForeignKey("report_runs.id", ondelete="CASCADE"))
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", server_default="PENDING")
    runtime_profile: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(100))
    model_name: Mapped[str] = mapped_column(String(200))
    model_digest: Mapped[str | None] = mapped_column(String(255))
    generation_parameters: Mapped[dict[str, Any]] = mapped_column(JSON)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    response_text: Mapped[str | None] = mapped_column(Text)
    response_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    output_schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    output_markdown: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(100))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
