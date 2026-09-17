"""Project-scoped content and saved query storage."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TimestampMixin
from app.db.types import UTCDateTime, utc_now


class Comment(IntegerPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "comments"
    __table_args__ = (
        UniqueConstraint("project_id", "ticket_id", "id", name="uq_comments_project_ticket_id"),
        ForeignKeyConstraint(
            ["project_id", "ticket_id"],
            ["tickets.project_id", "tickets.id"],
            name="fk_comments_ticket",
            ondelete="CASCADE",
        ),
        CheckConstraint("version > 0 AND body_schema_version > 0", name="positive_versions"),
        Index("ix_comments_ticket_created", "ticket_id", "created_at", "id"),
    )

    project_id: Mapped[int] = mapped_column(Integer)
    ticket_id: Mapped[int] = mapped_column(Integer)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    body: Mapped[str] = mapped_column(Text)
    body_schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    deleted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))

    __mapper_args__ = {"version_id_col": version}


class Mention(IntegerPrimaryKeyMixin, Base):
    __tablename__ = "mentions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "ticket_id"],
            ["tickets.project_id", "tickets.id"],
            name="fk_mentions_ticket",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["project_id", "ticket_id", "comment_id"],
            ["comments.project_id", "comments.ticket_id", "comments.id"],
            name="fk_mentions_comment",
            ondelete="CASCADE",
        ),
        Index(
            "uq_mentions_description_user",
            "ticket_id",
            "target_user_id",
            unique=True,
            sqlite_where=text("comment_id IS NULL"),
            postgresql_where=text("comment_id IS NULL"),
        ),
        UniqueConstraint("comment_id", "target_user_id", name="uq_mentions_comment_user"),
        Index("ix_mentions_inbox", "target_user_id", "removed_at", "read_at", "created_at"),
    )

    project_id: Mapped[int] = mapped_column(Integer)
    ticket_id: Mapped[int] = mapped_column(Integer)
    comment_id: Mapped[int | None] = mapped_column(Integer)
    target_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    mentioned_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    removed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Attachment(IntegerPrimaryKeyMixin, Base):
    __tablename__ = "attachments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "ticket_id"],
            ["tickets.project_id", "tickets.id"],
            name="fk_attachments_ticket",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "ticket_id", "comment_id"],
            ["comments.project_id", "comments.ticket_id", "comments.id"],
            name="fk_attachments_comment",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("storage_backend", "storage_key", name="uq_attachments_storage_key"),
        CheckConstraint("size_bytes >= 0", name="nonnegative_size"),
        CheckConstraint(
            "(deleted_at IS NULL AND purge_after IS NULL) OR "
            "(deleted_at IS NOT NULL AND purge_after IS NOT NULL AND purge_after >= deleted_at)",
            name="deletion_schedule",
        ),
        Index("ix_attachments_ticket", "project_id", "ticket_id", "deleted_at"),
        Index("ix_attachments_purge", "purge_after"),
    )

    project_id: Mapped[int] = mapped_column(Integer)
    ticket_id: Mapped[int] = mapped_column(Integer)
    comment_id: Mapped[int | None] = mapped_column(Integer)
    original_filename: Mapped[str] = mapped_column(String(512))
    media_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_backend: Mapped[str] = mapped_column(
        String(32), default="local", server_default="local"
    )
    storage_key: Mapped[str] = mapped_column(String(512))
    sha256: Mapped[str | None] = mapped_column(String(64))
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    deleted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    purge_after: Mapped[datetime | None] = mapped_column(UTCDateTime())


class SavedFilter(IntegerPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "saved_filters"
    __table_args__ = (
        CheckConstraint("visibility IN ('PERSONAL', 'PROJECT')", name="visibility_allowed"),
        CheckConstraint("schema_version > 0", name="positive_schema_version"),
        Index("ix_saved_filters_scope", "project_id", "visibility", "owner_id"),
    )

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(200))
    visibility: Mapped[str] = mapped_column(
        String(16), default="PERSONAL", server_default="PERSONAL"
    )
    schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)
