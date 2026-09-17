from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TimestampMixin
from app.db.types import UTCDateTime, utc_now


class SystemRole:
    USER = "USER"
    SYSTEM_ADMIN = "SYSTEM_ADMIN"


class Organization(IntegerPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"
    __table_args__ = (
        Index("ix_organizations_parent_id_name", "parent_id", "name"),
        Index(
            "uq_organizations_root_name",
            "name",
            unique=True,
            sqlite_where=text("parent_id IS NULL"),
            postgresql_where=text("parent_id IS NULL"),
        ),
        Index("uq_organizations_sibling_name", "parent_id", "name", unique=True),
    )

    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )

    parent: Mapped[Organization | None] = relationship(
        "Organization",
        back_populates="children",
        remote_side="Organization.id",
    )
    children: Mapped[list[Organization]] = relationship(
        "Organization",
        back_populates="parent",
    )
    users: Mapped[list[User]] = relationship("User", back_populates="organization")


class User(IntegerPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "system_role IN ('USER', 'SYSTEM_ADMIN')",
            name="system_role_allowed",
        ),
    )

    login_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, unique=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    system_role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=SystemRole.USER,
        server_default=SystemRole.USER,
    )
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    deactivated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization: Mapped[Organization] = relationship("Organization", back_populates="users")
    deactivated_by: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[deactivated_by_id],
        remote_side="User.id",
    )
    sessions: Mapped[list[UserSession]] = relationship(
        "UserSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    audit_events: Mapped[list[AuditLog]] = relationship(
        "AuditLog",
        back_populates="actor",
        foreign_keys="AuditLog.actor_user_id",
    )


class UserSession(IntegerPrimaryKeyMixin, Base):
    __tablename__ = "user_sessions"
    __table_args__ = (Index("ix_user_sessions_user_id_expires_at", "user_id", "expires_at"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="sessions")


class AuditLog(IntegerPrimaryKeyMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_target", "target_type", "target_id"),)

    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        index=True,
    )

    actor: Mapped[User | None] = relationship(
        "User",
        back_populates="audit_events",
        foreign_keys=[actor_user_id],
    )
