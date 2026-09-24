from datetime import date

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models import Comment, Mention, Project, ProjectMember, Ticket, User
from app.repositories.tickets import accessible_ticket_query, my_ticket_condition

OPEN_STATUSES = ("TODO", "IN_PROGRESS", "ON_HOLD")


def get_dashboard_counts(session: Session, actor_id: int, today: date, week_end: date):
    project_scope = select(ProjectMember.project_id).where(ProjectMember.user_id == actor_id)
    base = (
        Ticket.project_id.in_(project_scope),
        Ticket.deleted_at.is_(None),
        my_ticket_condition(actor_id),
        Ticket.status.in_(OPEN_STATUSES),
    )
    return session.execute(
        select(
            func.count(Ticket.id).label("open_mine"),
            func.count(Ticket.id)
            .filter(Ticket.due_date.is_not(None), Ticket.due_date < today)
            .label("overdue"),
            func.count(Ticket.id)
            .filter(Ticket.due_date.between(today, week_end))
            .label("due_this_week"),
        ).where(*base)
    ).one()


def list_recent_tickets(session: Session, actor_id: int, *, limit: int = 5):
    return session.execute(
        accessible_ticket_query(actor_id)
        .where(my_ticket_condition(actor_id))
        .order_by(Ticket.updated_at.desc(), Ticket.id.desc())
        .limit(limit)
    ).all()


def list_unread_mentions(session: Session, actor_id: int, *, limit: int = 5):
    mentioned_by = aliased(User)
    return (
        session.execute(
            select(
                Mention.id,
                Project.key.label("project_key"),
                Project.name.label("project_name"),
                Ticket.key.label("ticket_key"),
                mentioned_by.display_name.label("actor_display_name"),
                func.coalesce(Comment.body, Ticket.description).label("excerpt"),
                Mention.created_at,
                Mention.comment_id,
            )
            .join(Project, Project.id == Mention.project_id)
            .join(
                ProjectMember,
                and_(
                    ProjectMember.project_id == Mention.project_id,
                    ProjectMember.user_id == actor_id,
                ),
            )
            .join(
                Ticket,
                and_(
                    Ticket.project_id == Mention.project_id,
                    Ticket.id == Mention.ticket_id,
                ),
            )
            .join(mentioned_by, mentioned_by.id == Mention.mentioned_by_id)
            .outerjoin(Comment, Comment.id == Mention.comment_id)
            .where(
                Mention.target_user_id == actor_id,
                Mention.removed_at.is_(None),
                Mention.read_at.is_(None),
                Ticket.deleted_at.is_(None),
                or_(Mention.comment_id.is_(None), Comment.deleted_at.is_(None)),
            )
            .order_by(Mention.created_at.desc(), Mention.id.desc())
            .limit(limit)
        )
        .mappings()
        .all()
    )
