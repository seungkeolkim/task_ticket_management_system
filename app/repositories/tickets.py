from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, aliased

from app.models import Project, ProjectMember, Ticket, User


def project_scope(project_id: int, actor_id: int, *, override: bool):
    query = (
        select(Project.id)
        .outerjoin(
            ProjectMember,
            (ProjectMember.project_id == Project.id) & (ProjectMember.user_id == actor_id),
        )
        .where(Project.id == project_id)
    )
    if not override:
        query = query.where(ProjectMember.user_id == actor_id)
    return query


def ticket_query(project_id: int, actor_id: int, *, override: bool):
    creator = aliased(User)
    assignee = aliased(User)
    parent = aliased(Ticket)
    scope = project_scope(project_id, actor_id, override=override).subquery()
    return (
        select(
            Ticket,
            creator.id.label("creator_id"),
            creator.login_id.label("creator_login_id"),
            creator.display_name.label("creator_display_name"),
            assignee.id.label("assignee_id"),
            assignee.login_id.label("assignee_login_id"),
            assignee.display_name.label("assignee_display_name"),
            parent.key.label("parent_key"),
            parent.type.label("parent_type"),
            parent.title.label("parent_title"),
        )
        .join(creator, creator.id == Ticket.creator_id)
        .outerjoin(assignee, assignee.id == Ticket.assignee_id)
        .outerjoin(parent, parent.id == Ticket.parent_id)
        .where(
            Ticket.project_id.in_(select(scope.c.id)),
            Ticket.deleted_at.is_(None),
        )
    )


def ticket_rows(
    session: Session,
    project_id: int,
    actor_id: int,
    *,
    override: bool,
    query_text: str = "",
    page: int = 1,
    page_size: int = 20,
):
    query = ticket_query(project_id, actor_id, override=override)
    if query_text:
        query = query.where(
            or_(
                Ticket.key.icontains(query_text, autoescape=True),
                Ticket.title.icontains(query_text, autoescape=True),
            )
        )
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.execute(
        query.order_by(Ticket.updated_at.desc(), Ticket.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return rows, total


def ticket_row(
    session: Session,
    project_id: int,
    actor_id: int,
    ticket_key: str,
    *,
    override: bool,
):
    return session.execute(
        ticket_query(project_id, actor_id, override=override).where(Ticket.key == ticket_key)
    ).one_or_none()


def parent_ticket(
    session: Session,
    project_id: int,
    actor_id: int,
    ticket_key: str,
    *,
    override: bool,
) -> Ticket | None:
    scope = project_scope(project_id, actor_id, override=override).subquery()
    return session.scalar(
        select(Ticket).where(
            Ticket.project_id.in_(select(scope.c.id)),
            Ticket.key == ticket_key,
            Ticket.deleted_at.is_(None),
        )
    )


def assignee_is_active_member(session: Session, project_id: int, user_id: int) -> bool:
    return (
        session.scalar(
            select(ProjectMember.id)
            .join(User, User.id == ProjectMember.user_id)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
                User.is_active.is_(True),
            )
        )
        is not None
    )


def assignees(session: Session, project_id: int, actor_id: int, *, override: bool):
    scope = project_scope(project_id, actor_id, override=override).subquery()
    return (
        session.execute(
            select(User.id, User.login_id, User.display_name)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .where(
                ProjectMember.project_id.in_(select(scope.c.id)),
                User.is_active.is_(True),
            )
            .order_by(User.display_name, User.id)
        )
        .mappings()
        .all()
    )


def parent_candidates(session: Session, project_id: int, actor_id: int, *, override: bool):
    scope = project_scope(project_id, actor_id, override=override).subquery()
    return (
        session.execute(
            select(Ticket.key, Ticket.type, Ticket.title)
            .where(
                Ticket.project_id.in_(select(scope.c.id)),
                Ticket.type.in_(["EPIC", "TASK"]),
                Ticket.deleted_at.is_(None),
            )
            .order_by(Ticket.number)
        )
        .mappings()
        .all()
    )


def allocate_number(session: Session, project_id: int) -> int:
    next_value = session.scalar(
        update(Project)
        .where(Project.id == project_id)
        .values(next_ticket_number=Project.next_ticket_number + 1)
        .returning(Project.next_ticket_number)
        .execution_options(synchronize_session=False)
    )
    if next_value is None:
        raise RuntimeError("Project disappeared while allocating a ticket number")
    return next_value - 1
