"""SQLAlchemy ORM models.

Import model modules here as they are added so Alembic can discover their metadata.
"""

from app.models.content import Attachment, Comment, Mention, SavedFilter
from app.models.identity import AuditLog, Organization, SystemRole, User, UserSession
from app.models.reporting import (
    ReportAttempt,
    ReportRun,
    ReportRunProject,
    ReportSkill,
    ReportSkillVersion,
)
from app.models.work import (
    Project,
    ProjectMember,
    Ticket,
    TicketDeletionBatch,
    TicketHistory,
    TicketRelation,
)

__all__ = [
    "Attachment",
    "AuditLog",
    "Comment",
    "Mention",
    "Organization",
    "Project",
    "ProjectMember",
    "ReportAttempt",
    "ReportRun",
    "ReportRunProject",
    "ReportSkill",
    "ReportSkillVersion",
    "SavedFilter",
    "SystemRole",
    "Ticket",
    "TicketDeletionBatch",
    "TicketHistory",
    "TicketRelation",
    "User",
    "UserSession",
]
