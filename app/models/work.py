"""MVP work schema. Cross-row business rules are enforced by future services."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TimestampMixin
from app.db.types import UTCDateTime, utc_now
from app.domain.codes import HistoryEventType, Priority, ProjectRole, TicketStatus, TicketType


def allowed(column: str, values: Any, name: str) -> CheckConstraint:
    codes = ", ".join(f"'{item.value}'" for item in values)
    return CheckConstraint(f"{column} IN ({codes})", name=name)


class Project(IntegerPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (CheckConstraint("next_ticket_number > 0", name="positive_ticket_counter"),)

    key: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    next_ticket_number: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    history_complete_from: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ProjectMember(IntegerPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
        allowed("role", ProjectRole, "role_allowed"),
    )

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    role: Mapped[str] = mapped_column(
        String(32), default=ProjectRole.USER, server_default=ProjectRole.USER
    )


class TicketDeletionBatch(IntegerPrimaryKeyMixin, Base):
    __tablename__ = "ticket_deletion_batches"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_ticket_deletion_batches_project_id"),
        CheckConstraint("purge_after >= deleted_at", name="purge_after_deletion"),
        CheckConstraint(
            "restored_at IS NULL OR restored_at >= deleted_at", name="restore_after_deletion"
        ),
        CheckConstraint(
            "purged_at IS NULL OR (purged_at >= deleted_at AND restored_at IS NULL)",
            name="purge_not_restored",
        ),
        Index("ix_ticket_deletion_batches_purge", "restored_at", "purge_after"),
    )

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    root_ticket_key: Mapped[str] = mapped_column(String(64))
    deleted_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    deleted_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    purge_after: Mapped[datetime] = mapped_column(UTCDateTime())
    restored_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    purged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    restored_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class Ticket(IntegerPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_tickets_project_id"),
        UniqueConstraint("project_id", "number", name="uq_tickets_project_number"),
        ForeignKeyConstraint(
            ["project_id", "parent_id"],
            ["tickets.project_id", "tickets.id"],
            name="fk_tickets_project_parent",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "deletion_batch_id"],
            ["ticket_deletion_batches.project_id", "ticket_deletion_batches.id"],
            name="fk_tickets_project_deletion_batch",
            ondelete="RESTRICT",
        ),
        allowed("type", TicketType, "type_allowed"),
        allowed("status", TicketStatus, "status_allowed"),
        allowed("priority", Priority, "priority_allowed"),
        CheckConstraint("number > 0 AND version > 0", name="positive_number_version"),
        CheckConstraint("body_schema_version > 0", name="positive_body_version"),
        CheckConstraint("parent_id IS NULL OR parent_id != id", name="not_own_parent"),
        CheckConstraint(
            "(type = 'EPIC' AND parent_id IS NULL) OR type = 'TASK' OR "
            "(type = 'SUBTASK' AND parent_id IS NOT NULL)",
            name="parent_shape",
        ),
        CheckConstraint("progress_percent BETWEEN 0 AND 100", name="progress_range"),
        CheckConstraint(
            "planned_start_date IS NULL OR planned_end_date IS NULL OR "
            "planned_start_date <= planned_end_date",
            name="schedule_order",
        ),
        CheckConstraint(
            "(deleted_at IS NULL AND deletion_batch_id IS NULL) OR "
            "(deleted_at IS NOT NULL AND deletion_batch_id IS NOT NULL)",
            name="deletion_pair",
        ),
        Index("ix_tickets_project_status", "project_id", "deleted_at", "status"),
        Index("ix_tickets_project_parent", "project_id", "parent_id"),
        Index("ix_tickets_assignee_due", "assignee_id", "deleted_at", "due_date"),
        Index("ix_tickets_creator_updated", "creator_id", "deleted_at", "updated_at"),
        Index(
            "ix_tickets_project_schedule", "project_id", "planned_start_date", "planned_end_date"
        ),
    )

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    number: Mapped[int] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    type: Mapped[str] = mapped_column(String(16), default=TicketType.TASK, server_default="TASK")
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    body_schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    status: Mapped[str] = mapped_column(
        String(24), default=TicketStatus.TODO, server_default="TODO"
    )
    priority: Mapped[str] = mapped_column(
        String(16), default=Priority.MAJOR, server_default="MAJOR"
    )
    parent_id: Mapped[int | None] = mapped_column(Integer)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    due_date: Mapped[date | None] = mapped_column(Date)
    planned_start_date: Mapped[date | None] = mapped_column(Date)
    planned_end_date: Mapped[date | None] = mapped_column(Date)
    actual_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    progress_percent: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_milestone: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    sort_order: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    deletion_batch_id: Mapped[int | None] = mapped_column(Integer)

    __mapper_args__ = {"version_id_col": version}


class TicketRelation(IntegerPrimaryKeyMixin, Base):
    __tablename__ = "ticket_relations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "source_ticket_id"],
            ["tickets.project_id", "tickets.id"],
            name="fk_ticket_relations_source",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["project_id", "target_ticket_id"],
            ["tickets.project_id", "tickets.id"],
            name="fk_ticket_relations_target",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "project_id",
            "source_ticket_id",
            "target_ticket_id",
            "relation_type",
            name="uq_ticket_relations_endpoints_type",
        ),
        CheckConstraint("relation_type IN ('RELATED', 'DEPENDS_ON')", name="type_allowed"),
        CheckConstraint("source_ticket_id != target_ticket_id", name="different_endpoints"),
        CheckConstraint(
            "relation_type != 'RELATED' OR source_ticket_id < target_ticket_id",
            name="canonical_related_order",
        ),
        CheckConstraint(
            "(relation_type = 'RELATED' AND dependency_kind IS NULL AND lag_days = 0) OR "
            "(relation_type = 'DEPENDS_ON' AND dependency_kind IS NOT NULL AND "
            "dependency_kind IN ('FS', 'SS', 'FF', 'SF'))",
            name="dependency_shape",
        ),
        Index("ix_ticket_relations_target", "project_id", "target_ticket_id"),
    )

    project_id: Mapped[int] = mapped_column(Integer)
    source_ticket_id: Mapped[int] = mapped_column(Integer)
    target_ticket_id: Mapped[int] = mapped_column(Integer)
    relation_type: Mapped[str] = mapped_column(String(24))
    dependency_kind: Mapped[str | None] = mapped_column(String(2))
    lag_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class TicketHistory(IntegerPrimaryKeyMixin, Base):
    __tablename__ = "ticket_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "ticket_id"],
            ["tickets.project_id", "tickets.id"],
            name="fk_ticket_history_ticket",
            ondelete="CASCADE",
        ),
        UniqueConstraint("ticket_id", "ticket_version", name="uq_ticket_history_ticket_version"),
        allowed("event_type", HistoryEventType, "event_type_allowed"),
        CheckConstraint("ticket_version > 0 AND schema_version > 0", name="positive_versions"),
        Index("ix_ticket_history_period", "project_id", "occurred_at", "id"),
        Index("ix_ticket_history_ticket_time", "ticket_id", "occurred_at", "id"),
        Index("ix_ticket_history_operation", "operation_id"),
    )

    project_id: Mapped[int] = mapped_column(Integer)
    ticket_id: Mapped[int] = mapped_column(Integer)
    event_key: Mapped[str] = mapped_column(String(36), unique=True)
    operation_id: Mapped[str] = mapped_column(String(36))
    ticket_version: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    after_state: Mapped[dict[str, Any]] = mapped_column(JSON)
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
