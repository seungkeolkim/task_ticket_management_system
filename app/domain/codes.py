"""Stable persisted codes; presentation labels belong in the web layer."""

from enum import StrEnum


class ProjectRole(StrEnum):
    ADMIN = "PROJECT_ADMIN"
    USER = "PROJECT_USER"


class TicketType(StrEnum):
    EPIC = "EPIC"
    TASK = "TASK"
    SUBTASK = "SUBTASK"


class TicketStatus(StrEnum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    ON_HOLD = "ON_HOLD"
    CANCELLED = "CANCELLED"


class Priority(StrEnum):
    TRIVIAL = "TRIVIAL"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"
    BLOCKER = "BLOCKER"


class RelationType(StrEnum):
    RELATED = "RELATED"
    DEPENDS_ON = "DEPENDS_ON"


class HistoryEventType(StrEnum):
    CREATED = "CREATED"
    UPDATED = "UPDATED"
    STATUS_CHANGED = "STATUS_CHANGED"
    RELATION_CHANGED = "RELATION_CHANGED"
    CONTENT_CHANGED = "CONTENT_CHANGED"
    DELETED = "DELETED"
    RESTORED = "RESTORED"


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
