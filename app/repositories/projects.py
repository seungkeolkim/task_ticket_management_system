from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.domain.codes import ProjectRole, TicketStatus
from app.models import Project, ProjectMember, Ticket, User


def get_actor_status(session: Session, user_id: int):
    """actor 상태 정보를 조회한다."""
    return session.execute(
        select(User.is_active, User.must_change_password, User.system_role).where(
            User.id == user_id
        )
    ).one_or_none()


def build_project_access_query(actor_id: int, override: bool = False):
    """프로젝트 access query 구성한다."""
    query = select(Project, ProjectMember.role, ProjectMember.is_favorite).outerjoin(
        ProjectMember,
        (ProjectMember.project_id == Project.id) & (ProjectMember.user_id == actor_id),
    )
    if not override:
        query = query.where(ProjectMember.user_id == actor_id)
    return query.execution_options(populate_existing=True)


def accessible_project(session: Session, project_key: str, actor_id: int, override: bool):
    """프로젝트 접근 가능한 범위를 조회한다."""
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
    """프로젝트 목록을 조회한다."""
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
        query.order_by(Project.name, Project.id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return rows, total


def list_favorite_project_links(session: Session, actor_id: int):
    """공통 내비게이션에 표시할 사용자의 즐겨찾기 프로젝트를 조회한다."""
    return (
        session.execute(
            select(Project.key, Project.name)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(
                ProjectMember.user_id == actor_id,
                ProjectMember.is_favorite.is_(True),
            )
            .order_by(Project.name, Project.id)
        )
        .mappings()
        .all()
    )


def lock_project_membership(
    session: Session,
    project_key: str,
    user_id: int,
) -> ProjectMember | None:
    """즐겨찾기 변경 대상 프로젝트 참여 정보를 잠그고 반환한다."""
    query = (
        select(ProjectMember)
        .join(Project, Project.id == ProjectMember.project_id)
        .where(Project.key == project_key, ProjectMember.user_id == user_id)
    )
    if session.get_bind().dialect.name != "sqlite":
        query = query.with_for_update()
    return session.execute(query.execution_options(populate_existing=True)).scalar_one_or_none()


def active_user(session: Session, user_id: int) -> bool:
    """활성 사용자 정보를 조회한다."""
    return (
        session.scalar(select(User.id).where(User.id == user_id, User.is_active.is_(True)))
        is not None
    )


def duplicate_key(session: Session, key: str) -> bool:
    """key 중복 여부를 조회한다."""
    return session.scalar(select(Project.id).where(Project.key == key)) is not None


def duplicate_member(session: Session, project_id: int, user_id: int) -> bool:
    """구성원 중복 여부를 조회한다."""
    return (
        session.scalar(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
            )
        )
        is not None
    )


def lock_project_management(session: Session, project_id: int) -> Project:
    """프로젝트 기본 정보와 참여자 변경을 직렬화하고 최신 row를 반환한다."""
    query = select(Project).where(Project.id == project_id)
    if session.get_bind().dialect.name != "sqlite":
        query = query.with_for_update()
    return session.execute(query.execution_options(populate_existing=True)).scalar_one()


def project_member(session: Session, project_id: int, member_id: int):
    """프로젝트 범위에서 단일 참여자와 사용자 상태를 조회한다."""
    return session.execute(
        select(ProjectMember, User.is_active.label("user_is_active"))
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id, ProjectMember.id == member_id)
    ).one_or_none()


def project_administrator_count(session: Session, project_id: int) -> int:
    """프로젝트에 등록된 관리자 수를 반환한다."""
    return (
        session.scalar(
            select(func.count())
            .select_from(ProjectMember)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.role == ProjectRole.ADMIN,
            )
        )
        or 0
    )


def has_active_ticket_assignments(session: Session, project_id: int, user_id: int) -> bool:
    """사용자가 휴지통 밖의 미완료 티켓을 담당하는지 반환한다."""
    return (
        session.scalar(
            select(Ticket.id)
            .where(
                Ticket.project_id == project_id,
                Ticket.assignee_id == user_id,
                Ticket.deleted_at.is_(None),
                Ticket.status.notin_((TicketStatus.DONE, TicketStatus.CANCELLED)),
            )
            .limit(1)
        )
        is not None
    )


def project_member_view(session: Session, project_id: int, member_id: int):
    """역할 변경 결과로 반환할 단일 참여자 정보를 조회한다."""
    return session.execute(
        select(
            ProjectMember.id,
            User.id.label("user_id"),
            User.login_id,
            User.display_name,
            ProjectMember.role,
            User.is_active,
        )
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id, ProjectMember.id == member_id)
    ).mappings().one_or_none()


def list_project_members(
    session: Session, project_id: int, actor_id: int, *, override: bool = False
):
    """프로젝트 구성원 목록을 조회한다."""
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
    """후보 사용자 목록을 조회한다."""
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
