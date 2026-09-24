from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.models import Project, ProjectMember, User


def get_actor_status(session: Session, user_id: int):
    return session.execute(
        select(User.is_active, User.must_change_password, User.system_role).where(
            User.id == user_id
        )
    ).one_or_none()


def build_project_access_query(actor_id: int, override: bool = False):
    query = select(Project, ProjectMember.role).outerjoin(
        ProjectMember,
        (ProjectMember.project_id == Project.id) & (ProjectMember.user_id == actor_id),
    )
    if not override:
        query = query.where(ProjectMember.user_id == actor_id)
    return query.execution_options(populate_existing=True)


def accessible_project(session: Session, project_key: str, actor_id: int, override: bool):
    return session.execute(
        build_project_access_query(actor_id, override).where(Project.key == project_key)
    ).one_or_none()


def list_projects(
    session: Session,
    actor_id: int,
    include_all_projects: bool,
    search_query: str,
    page: int,
    page_size: int,
):
    query = build_project_access_query(actor_id, include_all_projects)
    if search_query:
        query = query.where(
            or_(
                Project.key.icontains(search_query, autoescape=True),
                Project.name.icontains(search_query, autoescape=True),
            )
        )
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.execute(
        query.order_by(Project.name, Project.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return rows, total


def active_user(session: Session, user_id: int) -> bool:
    return (
        session.scalar(select(User.id).where(User.id == user_id, User.is_active.is_(True)))
        is not None
    )


def duplicate_key(session: Session, key: str) -> bool:
    return session.scalar(select(Project.id).where(Project.key == key)) is not None


def duplicate_member(session: Session, project_id: int, user_id: int) -> bool:
    return (
        session.scalar(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
            )
        )
        is not None
    )


def list_project_members(
    session: Session, project_id: int, actor_id: int, *, override: bool = False
):
    accessible_projects = (
        build_project_access_query(actor_id, override).with_only_columns(Project.id).subquery()
    )
    return (
        session.execute(
            select(
                ProjectMember.id,
                User.id.label("user_id"),
                User.login_id,
                User.display_name,
                ProjectMember.role,
                User.is_active,
            )
            .join(User, User.id == ProjectMember.user_id)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.project_id.in_(select(accessible_projects.c.id)),
            )
            .order_by(User.display_name, User.id)
        )
        .mappings()
        .all()
    )


def list_candidate_users(session: Session, search_query: str, project_id: int | None):
    query = select(User.id, User.login_id, User.display_name).where(User.is_active.is_(True))
    if project_id is not None:
        query = query.where(
            ~exists().where(
                ProjectMember.project_id == project_id, ProjectMember.user_id == User.id
            )
        )
    if search_query:
        query = query.where(
            or_(
                User.login_id.icontains(search_query, autoescape=True),
                User.display_name.icontains(search_query, autoescape=True),
            )
        )
    return session.execute(query.order_by(User.display_name, User.id).limit(50)).mappings().all()
