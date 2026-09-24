from datetime import date

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session, aliased

from app.domain.codes import ProjectRole
from app.models import Project, ProjectMember, Ticket, TicketRelation, User


def project_scope(project_id: int, actor_id: int, *, override: bool):
    """사용자가 접근 가능한 단일 프로젝트 scope를 구성한다."""
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


def member_project_scope(actor_id: int):
    """사용자가 구성원인 프로젝트 scope를 구성한다."""
    return select(ProjectMember.project_id).where(ProjectMember.user_id == actor_id)


def my_ticket_condition(actor_id: int):
    """현재 사용자의 내 티켓 조회 조건을 구성한다."""
    return or_(
        Ticket.assignee_id == actor_id,
        and_(Ticket.assignee_id.is_(None), Ticket.creator_id == actor_id),
    )


def _ticket_select():
    """티켓과 표시용 연관 정보를 조회하는 select를 구성한다."""
    creator = aliased(User)
    assignee = aliased(User)
    parent = aliased(Ticket)
    return (
        select(
            Ticket,
            Project.key.label("project_key"),
            Project.name.label("project_name"),
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
        .join(Project, Project.id == Ticket.project_id)
        .join(creator, creator.id == Ticket.creator_id)
        .outerjoin(assignee, assignee.id == Ticket.assignee_id)
        .outerjoin(
            parent,
            (parent.id == Ticket.parent_id)
            & (parent.project_id == Ticket.project_id)
            & parent.deleted_at.is_(None),
        )
    )


def ticket_query(project_id: int, actor_id: int, *, override: bool):
    """프로젝트 권한이 적용된 티켓 query를 구성한다."""
    scope = project_scope(project_id, actor_id, override=override).subquery()
    return _ticket_select().where(
        Ticket.project_id.in_(select(scope.c.id)),
        Ticket.deleted_at.is_(None),
    )


def accessible_ticket_query(actor_id: int):
    """티켓 query 접근 가능한 범위를 조회한다."""
    scope = member_project_scope(actor_id).subquery()
    return _ticket_select().where(
        Ticket.project_id.in_(select(scope.c.project_id)),
        Ticket.deleted_at.is_(None),
    )


def filtered_ticket_rows(
    session: Session,
    actor_id: int,
    *,
    scope_name: str,
    status: str,
    due: str,
    today: date,
    week_end: date,
    query_text: str = "",
    page: int = 1,
    page_size: int = 20,
):
    """티켓 rows 필터링해 조회한다."""
    query = accessible_ticket_query(actor_id)
    if scope_name == "mine":
        query = query.where(my_ticket_condition(actor_id))
    elif scope_name == "created":
        query = query.where(Ticket.creator_id == actor_id)
    if status == "open":
        query = query.where(Ticket.status.notin_(["DONE", "CANCELLED"]))
    if due == "overdue":
        query = query.where(Ticket.due_date.is_not(None), Ticket.due_date < today)
    elif due == "this_week":
        query = query.where(Ticket.due_date.between(today, week_end))
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


def board_rows(session: Session, project_id: int, actor_id: int, *, override: bool):
    """보드에 표시할 티켓 row를 조회한다."""
    return session.execute(
        ticket_query(project_id, actor_id, override=override).order_by(
            Ticket.sort_order, Ticket.number, Ticket.id
        )
    ).all()


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
    """프로젝트 티켓 목록 row를 검색·조회한다."""
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
    """권한 범위에서 단일 티켓 row를 조회한다."""
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
    """권한 범위에서 상위 티켓을 조회한다."""
    scope = project_scope(project_id, actor_id, override=override).subquery()
    return session.scalar(
        select(Ticket).where(
            Ticket.project_id.in_(select(scope.c.id)),
            Ticket.key == ticket_key,
            Ticket.deleted_at.is_(None),
        )
    )


def assignee_is_active_member(session: Session, project_id: int, user_id: int) -> bool:
    """담당자가 활성 프로젝트 구성원인지 확인한다."""
    return (
        session.scalar(
            select(ProjectMember.id)
            .join(User, User.id == ProjectMember.user_id)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
                ProjectMember.role != ProjectRole.GUEST,
                User.is_active.is_(True),
            )
        )
        is not None
    )


def assignees(session: Session, project_id: int, actor_id: int, *, override: bool):
    """지정 가능한 활성 담당자 후보를 조회한다."""
    scope = project_scope(project_id, actor_id, override=override).subquery()
    return (
        session.execute(
            select(User.id, User.login_id, User.display_name)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .where(
                ProjectMember.project_id.in_(select(scope.c.id)),
                ProjectMember.role != ProjectRole.GUEST,
                User.is_active.is_(True),
            )
            .order_by(User.display_name, User.id)
        )
        .mappings()
        .all()
    )


def parent_candidates(
    session: Session,
    project_id: int,
    actor_id: int,
    *,
    override: bool,
    allowed_types: tuple[str, ...] = ("EPIC", "TASK"),
    exclude_ticket_id: int | None = None,
):
    """유형과 권한에 맞는 상위 티켓 후보를 조회한다."""
    scope = project_scope(project_id, actor_id, override=override).subquery()
    query = select(Ticket.key, Ticket.type, Ticket.title).where(
        Ticket.project_id.in_(select(scope.c.id)),
        Ticket.type.in_(allowed_types),
        Ticket.deleted_at.is_(None),
    )
    if exclude_ticket_id is not None:
        query = query.where(Ticket.id != exclude_ticket_id)
    return session.execute(query.order_by(Ticket.number)).mappings().all()


def parent_would_cycle(
    session: Session, project_id: int, ticket_id: int, parent_id: int | None
) -> bool:
    """상위 티켓 변경이 계층 순환을 만드는지 확인한다."""
    seen = {ticket_id}
    current_id = parent_id
    while current_id is not None:
        if current_id in seen:
            return True
        seen.add(current_id)
        current_id = session.scalar(
            select(Ticket.parent_id).where(
                Ticket.project_id == project_id,
                Ticket.id == current_id,
            )
        )
    return False


def relation_rows(session: Session, project_id: int, ticket_id: int):
    """티켓의 정방향·역방향 관계 row를 조회한다."""
    source = aliased(Ticket)
    target = aliased(Ticket)
    return session.execute(
        select(
            source.key.label("source_ticket_key"),
            target.key.label("target_ticket_key"),
            TicketRelation.relation_type,
            TicketRelation.dependency_kind,
            TicketRelation.lag_days,
        )
        .join(
            source,
            (source.project_id == TicketRelation.project_id)
            & (source.id == TicketRelation.source_ticket_id),
        )
        .join(
            target,
            (target.project_id == TicketRelation.project_id)
            & (target.id == TicketRelation.target_ticket_id),
        )
        .where(
            TicketRelation.project_id == project_id,
            or_(
                TicketRelation.source_ticket_id == ticket_id,
                TicketRelation.target_ticket_id == ticket_id,
            ),
        )
        .order_by(TicketRelation.id)
    ).mappings().all()


def incomplete_dependency_count(session: Session, project_id: int, ticket_id: int) -> int:
    """티켓의 미완료 의존 대상 수를 조회한다."""
    target = aliased(Ticket)
    return (
        session.scalar(
            select(func.count())
            .select_from(TicketRelation)
            .join(
                target,
                (target.project_id == TicketRelation.project_id)
                & (target.id == TicketRelation.target_ticket_id),
            )
            .where(
                TicketRelation.project_id == project_id,
                TicketRelation.source_ticket_id == ticket_id,
                TicketRelation.relation_type == "DEPENDS_ON",
                target.status != "DONE",
            )
        )
        or 0
    )


def incomplete_dependency_source_ids(session: Session, project_id: int) -> set[int]:
    """미완료 의존성을 가진 티켓 ID를 조회한다."""
    target = aliased(Ticket)
    return set(
        session.scalars(
            select(TicketRelation.source_ticket_id)
            .join(
                target,
                (target.project_id == TicketRelation.project_id)
                & (target.id == TicketRelation.target_ticket_id),
            )
            .where(
                TicketRelation.project_id == project_id,
                TicketRelation.relation_type == "DEPENDS_ON",
                target.status != "DONE",
            )
            .distinct()
        )
    )


def incomplete_child_count(session: Session, project_id: int, epic_id: int) -> int:
    """Epic의 미완료 하위 Task 수를 조회한다."""
    return (
        session.scalar(
            select(func.count())
            .select_from(Ticket)
            .where(
                Ticket.project_id == project_id,
                Ticket.parent_id == epic_id,
                Ticket.type == "TASK",
                Ticket.status != "DONE",
                Ticket.deleted_at.is_(None),
            )
        )
        or 0
    )


def allocate_number(session: Session, project_id: int) -> int:
    """프로젝트의 다음 티켓 번호를 원자적으로 할당한다."""
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
