import logging
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.types import utc_now
from app.domain.auth import AuthError, Identity
from app.domain.codes import (
    HistoryEventType,
    Priority,
    ProjectRole,
    RelationType,
    TicketStatus,
    TicketType,
)
from app.models import AuditLog, Ticket, TicketHistory, TicketRelation
from app.repositories import tickets as repository
from app.schemas.contracts import FieldChange, RelationSnapshot, TicketEvent, TicketState
from app.schemas.tickets import (
    BoardCard,
    BoardColumn,
    BoardDetachedGroup,
    BoardEpicGroup,
    BoardStatusOption,
    BoardTask,
    BoardView,
    TicketCreate,
    TicketCreateOptions,
    TicketDetailView,
    TicketEditOptions,
    TicketPage,
    TicketParentView,
    TicketRelationCreate,
    TicketRelationDelete,
    TicketRelationTargetView,
    TicketRelationView,
    TicketTransition,
    TicketUpdate,
    TicketUserView,
    TicketView,
)
from app.services import projects as project_service

logger = logging.getLogger(__name__)

TYPE_LABELS = {
    TicketType.EPIC: "Epic",
    TicketType.TASK: "Task",
    TicketType.SUBTASK: "Subtask",
}
STATUS_LABELS = {
    TicketStatus.TODO: ("등록", "todo"),
    TicketStatus.IN_PROGRESS: ("진행중", "progress"),
    TicketStatus.DONE: ("완료", "done"),
    TicketStatus.ON_HOLD: ("보류", "hold"),
    TicketStatus.CANCELLED: ("취소", "cancelled"),
}
BOARD_STATUSES = (
    TicketStatus.TODO,
    TicketStatus.IN_PROGRESS,
    TicketStatus.ON_HOLD,
    TicketStatus.DONE,
    TicketStatus.CANCELLED,
)
PRIORITY_LABELS = {
    Priority.TRIVIAL: "Trivial",
    Priority.MINOR: "Minor",
    Priority.MAJOR: "Major",
    Priority.CRITICAL: "Critical",
    Priority.BLOCKER: "Blocker",
}
RELATION_LABELS = {
    RelationType.RELATED: "관계 있음",
    RelationType.DEPENDS_ON: "의존함",
}
TERMINAL_STATUSES = {TicketStatus.DONE, TicketStatus.CANCELLED}
FSM_TRANSITIONS = {
    TicketStatus.TODO: (TicketStatus.IN_PROGRESS, TicketStatus.ON_HOLD, TicketStatus.CANCELLED),
    TicketStatus.IN_PROGRESS: (TicketStatus.DONE, TicketStatus.ON_HOLD, TicketStatus.CANCELLED),
    TicketStatus.ON_HOLD: (TicketStatus.TODO, TicketStatus.IN_PROGRESS, TicketStatus.CANCELLED),
    TicketStatus.DONE: (TicketStatus.IN_PROGRESS,),
    TicketStatus.CANCELLED: (TicketStatus.TODO,),
}


def record_ticket_audit_event(
    session: Session, action: str, actor_id: int, ticket: Ticket, **details: object
) -> None:
    """티켓 변경 감사 event를 기록한다."""
    session.add(
        AuditLog(
            action=action,
            actor_user_id=actor_id,
            target_type="ticket",
            target_id=ticket.key,
            details={
                "project_id": ticket.project_id,
                "ticket_id": ticket.id,
                "type": ticket.type,
                **details,
            },
        )
    )


def uses_system_administrator_override(project) -> bool:
    """프로젝트 접근이 시스템 관리자 override인지 확인한다."""
    return project.role is None and project.can_manage


def _build_ticket_user_view(user_id: int | None, login_id: str | None, display_name: str | None):
    """티켓 사용자 정보를 view로 변환한다."""
    if user_id is None:
        return None
    return TicketUserView(id=user_id, login_id=login_id or "", display_name=display_name or "")


def build_ticket_view(ticket_row) -> TicketView:
    """티켓 row를 상세 view로 변환한다."""
    ticket = ticket_row[0]
    mapping = ticket_row._mapping
    ticket_type = TicketType(ticket.type)
    status = TicketStatus(ticket.status)
    priority = Priority(ticket.priority)
    status_label, status_code = STATUS_LABELS[status]
    parent = None
    if mapping["parent_key"] is not None:
        parent = TicketParentView(
            key=mapping["parent_key"],
            type=TicketType(mapping["parent_type"]),
            title=mapping["parent_title"],
        )
    return TicketView(
        id=ticket.id,
        project_id=ticket.project_id,
        project_key=mapping["project_key"],
        project_name=mapping["project_name"],
        number=ticket.number,
        key=ticket.key,
        type=ticket_type,
        type_label=TYPE_LABELS[ticket_type],
        title=ticket.title,
        description=ticket.description,
        status=status,
        status_label=status_label,
        status_code=status_code,
        priority=priority,
        priority_label=PRIORITY_LABELS[priority],
        priority_code=priority.value.lower(),
        parent=parent,
        creator=_build_ticket_user_view(
            mapping["creator_id"], mapping["creator_login_id"], mapping["creator_display_name"]
        ),
        assignee=_build_ticket_user_view(
            mapping["assignee_id"], mapping["assignee_login_id"], mapping["assignee_display_name"]
        ),
        due_date=ticket.due_date,
        actual_started_at=ticket.actual_started_at,
        completed_at=ticket.completed_at,
        cancelled_at=ticket.cancelled_at,
        version=ticket.version,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


def build_ticket_detail_view(
    session: Session, ticket_row, actor_id: int, *, override: bool
) -> TicketDetailView:
    """티켓 기본 정보와 정·역방향 관계를 상세 view로 변환한다."""
    ticket = ticket_row[0]
    relations: list[TicketRelationView] = []
    for relation_row in repository.relation_view_rows(
        session, ticket.project_id, ticket.id, actor_id, override=override
    ):
        relation_type = RelationType(relation_row["relation_type"])
        current_is_source = relation_row["source_ticket_id"] == ticket.id
        if current_is_source:
            related_ticket_key = relation_row["target_ticket_key"]
            related_ticket_title = relation_row["target_ticket_title"]
            related_ticket_status = TicketStatus(relation_row["target_ticket_status"])
        else:
            related_ticket_key = relation_row["source_ticket_key"]
            related_ticket_title = relation_row["source_ticket_title"]
            related_ticket_status = TicketStatus(relation_row["source_ticket_status"])

        if relation_type == RelationType.RELATED:
            direction = "RELATED"
            direction_label = "관계 있음"
        elif current_is_source:
            direction = "OUTGOING"
            direction_label = "이 티켓이 의존함"
        else:
            direction = "INCOMING"
            direction_label = "이 티켓에 의존함"
        related_status_label, related_status_code = STATUS_LABELS[related_ticket_status]
        relations.append(
            TicketRelationView(
                id=relation_row["id"],
                relation_type=relation_type,
                relation_label=RELATION_LABELS[relation_type],
                direction=direction,
                direction_label=direction_label,
                ticket=TicketRelationTargetView(
                    key=related_ticket_key,
                    title=related_ticket_title,
                    status=related_ticket_status,
                    status_label=related_status_label,
                    status_code=related_status_code,
                ),
                created_at=relation_row["created_at"],
            )
        )
    return TicketDetailView(**build_ticket_view(ticket_row).model_dump(), relations=relations)


def _build_board_card(
    ticket: TicketView, *, can_transition: bool, completion_blocked: bool
) -> BoardCard:
    """티켓 view와 전이 권한으로 보드 카드를 구성한다."""
    return BoardCard(
        key=ticket.key,
        version=ticket.version,
        type=ticket.type,
        type_label=ticket.type_label,
        title=ticket.title,
        status=ticket.status,
        status_label=ticket.status_label,
        status_code=ticket.status_code,
        priority=ticket.priority,
        priority_label=ticket.priority_label,
        priority_code=ticket.priority_code,
        assignee=ticket.assignee,
        due_date=ticket.due_date,
        can_transition=can_transition,
        allowed_statuses=list(get_allowed_transitions(ticket.status)) if can_transition else [],
        completion_blocked=completion_blocked,
    )


def _build_ticket_state_snapshot(
    ticket: Ticket, parent_key: str | None, relations: list[RelationSnapshot] | None = None
) -> TicketState:
    """티켓의 현재 업무 상태 snapshot을 구성한다."""
    return TicketState(
        ticket_key=ticket.key,
        project_id=ticket.project_id,
        version=ticket.version,
        type=ticket.type,
        title=ticket.title,
        description=ticket.description,
        status=ticket.status,
        priority=ticket.priority,
        parent_key=parent_key,
        creator_id=ticket.creator_id,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        assignee_id=ticket.assignee_id,
        due_date=ticket.due_date,
        planned_start_date=ticket.planned_start_date,
        planned_end_date=ticket.planned_end_date,
        actual_started_at=ticket.actual_started_at,
        completed_at=ticket.completed_at,
        cancelled_at=ticket.cancelled_at,
        progress_percent=ticket.progress_percent,
        is_milestone=ticket.is_milestone,
        sort_order=str(ticket.sort_order),
        deleted_at=ticket.deleted_at,
        relations=relations or [],
    )


def _build_ticket_creation_history(
    ticket: Ticket, parent_key: str | None, actor_id: int
) -> TicketHistory:
    """티켓 생성 이력 event를 구성한다."""
    state = _build_ticket_state_snapshot(ticket, parent_key)
    event = TicketEvent(
        event_key=uuid4(),
        operation_id=uuid4(),
        ticket_key=ticket.key,
        project_id=ticket.project_id,
        ticket_version=ticket.version,
        event_type=HistoryEventType.CREATED,
        actor_id=actor_id,
        occurred_at=ticket.created_at,
        before_state=None,
        after_state=state,
        changes=[FieldChange(field="ticket", before=None, after=state.model_dump(mode="json"))],
    )
    return TicketHistory(
        project_id=ticket.project_id,
        ticket_id=ticket.id,
        event_key=str(event.event_key),
        operation_id=str(event.operation_id),
        ticket_version=ticket.version,
        event_type=event.event_type,
        actor_id=actor_id,
        occurred_at=event.occurred_at,
        schema_version=event.schema_version,
        before_state=None,
        after_state=event.after_state.model_dump(mode="json"),
        changes=[change.model_dump(mode="json") for change in event.changes],
    )


def _build_ticket_snapshot(session: Session, ticket: Ticket, parent_key: str | None) -> TicketState:
    """티켓과 관계를 포함한 상태 snapshot을 구성한다."""
    relations = [
        RelationSnapshot(**row)
        for row in repository.relation_rows(session, ticket.project_id, ticket.id)
    ]
    return _build_ticket_state_snapshot(ticket, parent_key, relations)


def _build_ticket_change_history(
    ticket: Ticket,
    actor_id: int,
    event_type: HistoryEventType,
    before: TicketState,
    after: TicketState,
    fields: tuple[str, ...],
    operation_id: UUID | None = None,
) -> TicketHistory:
    """변경 전후 snapshot으로 티켓 이력을 구성한다."""
    before_data = before.model_dump(mode="json")
    after_data = after.model_dump(mode="json")
    changes = [
        FieldChange(field=field, before=before_data[field], after=after_data[field])
        for field in fields
        if before_data[field] != after_data[field]
    ]
    event = TicketEvent(
        event_key=uuid4(),
        operation_id=operation_id or uuid4(),
        ticket_key=ticket.key,
        project_id=ticket.project_id,
        ticket_version=ticket.version,
        event_type=event_type,
        actor_id=actor_id,
        occurred_at=ticket.updated_at,
        before_state=before,
        after_state=after,
        changes=changes,
    )
    return TicketHistory(
        project_id=ticket.project_id,
        ticket_id=ticket.id,
        event_key=str(event.event_key),
        operation_id=str(event.operation_id),
        ticket_version=ticket.version,
        event_type=event.event_type,
        actor_id=actor_id,
        occurred_at=event.occurred_at,
        schema_version=event.schema_version,
        before_state=event.before_state.model_dump(mode="json"),
        after_state=event.after_state.model_dump(mode="json"),
        changes=[change.model_dump(mode="json") for change in event.changes],
    )


def _get_project(session: Session, actor: Identity, project_key: str):
    """읽기 가능한 프로젝트를 조회한다."""
    return project_service.require_project_member(session, actor, project_key)


def _get_writable_project(session: Session, actor: Identity, project_key: str):
    """쓰기 가능한 프로젝트를 조회한다."""
    return project_service.require_project_user_access(session, actor, project_key)


def get_allowed_transitions(status: TicketStatus | str) -> tuple[TicketStatus, ...]:
    """현재 상태에서 허용되는 다음 상태를 반환한다."""
    return FSM_TRANSITIONS[TicketStatus(status)]


def can_edit_ticket(project_view, ticket: Ticket | TicketView, actor: Identity) -> bool:
    """현재 사용자의 티켓 편집 가능 여부를 반환한다."""
    return (
        project_view.role in {ProjectRole.ADMIN, ProjectRole.USER}
        or project_view.can_manage
    )


def _require_active_project(project) -> None:
    """프로젝트가 활성 상태인지 검증한다."""
    if not project.is_active:
        raise AuthError("project_inactive", "비활성 프로젝트의 티켓은 변경할 수 없습니다.", 409)


def _require_expected_version(ticket: Ticket, expected_version: int) -> None:
    """요청 version과 현재 티켓 version이 같은지 검증한다."""
    if ticket.version != expected_version:
        raise AuthError(
            "ticket_version_conflict",
            "다른 사용자가 먼저 변경했습니다. 최신 내용을 다시 불러오세요.",
            409,
        )


def _require_relation_ticket_editable(ticket: Ticket) -> None:
    """관계 변경 대상 티켓이 종료 상태가 아닌지 검증한다."""
    if TicketStatus(ticket.status) in TERMINAL_STATUSES:
        raise AuthError(
            "terminal_ticket_relation_locked",
            "완료·취소 티켓의 관계는 재개한 후 변경할 수 있습니다.",
            409,
        )


def _get_ticket_row(session: Session, actor: Identity, project_view, ticket_key: str):
    """프로젝트 권한 범위에서 티켓 row를 조회한다."""
    ticket_row = repository.ticket_row(
        session,
        project_view.id,
        actor.id,
        ticket_key.strip().upper(),
        override=uses_system_administrator_override(project_view),
    )
    if ticket_row is None:
        raise AuthError("ticket_not_found", "티켓을 찾을 수 없습니다.", 404)
    return ticket_row


def _parent_for_update(
    session: Session, actor: Identity, project, ticket: Ticket, parent_key: str | None
) -> Ticket | None:
    """변경 요청에 맞는 상위 티켓을 조회하고 검증한다."""
    if ticket.type == TicketType.EPIC:
        if parent_key is not None:
            raise AuthError("invalid_parent", "Epic은 상위 티켓을 가질 수 없습니다.")
        return None
    if ticket.type == TicketType.SUBTASK and parent_key is None:
        raise AuthError("invalid_parent", "Subtask는 상위 Task가 필요합니다.")
    if parent_key is None:
        return None
    parent = repository.parent_ticket(
        session,
        project.id,
        actor.id,
        parent_key,
        override=uses_system_administrator_override(project),
    )
    if parent is None:
        raise AuthError("invalid_parent", "유효한 상위 티켓을 선택하세요.")
    expected_type = TicketType.EPIC if ticket.type == TicketType.TASK else TicketType.TASK
    if parent.type != expected_type:
        raise AuthError(
            "invalid_parent",
            "Task의 상위 티켓은 Epic이어야 합니다."
            if ticket.type == TicketType.TASK
            else "Subtask의 상위 티켓은 Task여야 합니다.",
        )
    if repository.parent_would_cycle(session, project.id, ticket.id, parent.id):
        raise AuthError("invalid_parent", "순환 계층은 만들 수 없습니다.")
    return parent


def list_project_tickets(
    session: Session,
    actor: Identity,
    project_key: str,
    *,
    search_query: str = "",
    page: int = 1,
    page_size: int | None = None,
):
    """프로젝트 티켓 목록을 조회한다."""
    size = page_size if page_size is not None else get_settings().pagination.default_size
    if (
        len(search_query) > 200
        or not 1 <= page <= 1_000_000
        or size not in {10, 20, 50}
    ):
        raise AuthError("invalid_filter", "검색 조건과 페이지 범위를 확인하세요.")
    with project_service.project_operation_context(session, actor, "ticket_list"):
        project = _get_project(session, actor, project_key)
        rows, total = repository.ticket_rows(
            session,
            project.id,
            actor.id,
            override=uses_system_administrator_override(project),
            query_text=search_query.strip(),
            page=page,
            page_size=size,
        )
        return project, TicketPage(
            tickets=[build_ticket_view(ticket_row) for ticket_row in rows],
            total=total,
            page=page,
            page_size=size,
        )


def list_global_tickets(
    session: Session,
    actor: Identity,
    *,
    scope: str = "mine",
    status: str = "open",
    due: str = "all",
    search_query: str = "",
    page: int = 1,
    page_size: int | None = None,
):
    """전체 티켓 목록을 조회한다."""
    size = page_size if page_size is not None else get_settings().pagination.default_size
    if (
        scope not in {"mine", "created", "all"}
        or status not in {"open", "all"}
        or due not in {"all", "overdue", "this_week"}
        or len(search_query) > 200
        or not 1 <= page <= 1_000_000
        or size not in {10, 20, 50}
    ):
        raise AuthError("invalid_filter", "검색 조건과 페이지 범위를 확인하세요.")
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    week_end = today + timedelta(days=6 - today.weekday())
    with project_service.project_operation_context(session, actor, "global_ticket_list"):
        project_service.is_system_administrator(session, actor)
        rows, total = repository.filtered_ticket_rows(
            session,
            actor.id,
            scope_name=scope,
            status=status,
            due=due,
            today=today,
            week_end=week_end,
            query_text=search_query.strip(),
            page=page,
            page_size=size,
        )
        return TicketPage(
            tickets=[build_ticket_view(ticket_row) for ticket_row in rows],
            total=total,
            page=page,
            page_size=size,
        )


def build_ticket_board(session: Session, actor: Identity, project_key: str):
    """티켓 보드 구성한다."""
    with project_service.project_operation_context(session, actor, "ticket_board"):
        project = _get_project(session, actor, project_key)
        rows = repository.board_rows(
            session, project.id, actor.id, override=uses_system_administrator_override(project)
        )
        indexed = {
            ticket_row[0].id: (ticket_row[0], build_ticket_view(ticket_row))
            for ticket_row in rows
        }
        dependency_blocked_ids = repository.incomplete_dependency_source_ids(session, project.id)

        def board_card(item: tuple[Ticket, TicketView]) -> BoardCard:
            """티켓과 전이 권한으로 보드 카드를 구성한다."""
            ticket_row, ticket_view = item
            return _build_board_card(
                ticket_view,
                can_transition=project.is_active and can_edit_ticket(project, ticket_row, actor),
                completion_blocked=ticket_row.id in dependency_blocked_ids,
            )

        epics = [item for item in indexed.values() if item[0].type == TicketType.EPIC]
        tasks = [item for item in indexed.values() if item[0].type == TicketType.TASK]
        subtasks_by_parent: dict[int, list[tuple[Ticket, TicketView]]] = {}
        for item in indexed.values():
            row, _ = item
            if row.type == TicketType.SUBTASK and row.parent_id in indexed:
                subtasks_by_parent.setdefault(row.parent_id, []).append(item)

        groups: list[BoardEpicGroup] = []
        for epic_item in [*epics, None]:
            epic_id = epic_item[0].id if epic_item else None
            group_tasks = [
                item
                for item in tasks
                if (item[0].parent_id if item[0].parent_id in indexed else None) == epic_id
            ]
            columns: list[BoardColumn] = []
            for ticket_status in BOARD_STATUSES:
                label, code = STATUS_LABELS[ticket_status]
                task_cards: list[BoardTask] = []
                detached: list[BoardDetachedGroup] = []
                for task_row, task_view in group_tasks:
                    children = subtasks_by_parent.get(task_row.id, [])
                    if task_row.status == ticket_status:
                        task_cards.append(
                            BoardTask(
                                card=board_card((task_row, task_view)),
                                subtasks=[
                                    board_card((child_row, child_view))
                                    for child_row, child_view in children
                                    if child_row.status == ticket_status
                                ],
                            )
                        )
                    other_status_children = [
                        board_card((child_row, child_view))
                        for child_row, child_view in children
                        if child_row.status == ticket_status and task_row.status != ticket_status
                    ]
                    if other_status_children:
                        detached.append(
                            BoardDetachedGroup(
                                parent_key=task_view.key,
                                parent_title=task_view.title,
                                subtasks=other_status_children,
                            )
                        )
                columns.append(
                    BoardColumn(
                        status=ticket_status,
                        label=label,
                        code=code,
                        card_count=sum(1 + len(task.subtasks) for task in task_cards)
                        + sum(len(group.subtasks) for group in detached),
                        tasks=task_cards,
                        detached_groups=detached,
                    )
                )
            groups.append(
                BoardEpicGroup(
                    key=epic_item[1].key if epic_item else None,
                    title=epic_item[1].title if epic_item else "Epic 없음",
                    columns=columns,
                )
            )
        return project, BoardView(
            groups=groups,
            statuses=[
                BoardStatusOption(
                    status=status, label=STATUS_LABELS[status][0], code=STATUS_LABELS[status][1]
                )
                for status in BOARD_STATUSES
            ],
        )


def get_ticket_detail(session: Session, actor: Identity, project_key: str, ticket_key: str):
    """티켓 상세 정보를 조회한다."""
    with project_service.project_operation_context(session, actor, "ticket_read"):
        project = _get_project(session, actor, project_key)
        ticket_row = _get_ticket_row(session, actor, project, ticket_key)
        return project, build_ticket_detail_view(
            session,
            ticket_row,
            actor.id,
            override=uses_system_administrator_override(project),
        )


def _relation_endpoint_rows(session: Session, actor: Identity, project, relation: TicketRelation):
    """관계의 양 끝 티켓 row를 현재 프로젝트 권한 범위에서 조회한다."""
    override = uses_system_administrator_override(project)
    source_row = repository.ticket_row_by_id(
        session,
        project.id,
        actor.id,
        relation.source_ticket_id,
        override=override,
    )
    target_row = repository.ticket_row_by_id(
        session,
        project.id,
        actor.id,
        relation.target_ticket_id,
        override=override,
    )
    if source_row is None or target_row is None:
        raise AuthError("ticket_relation_not_found", "티켓 관계를 찾을 수 없습니다.", 404)
    return source_row, target_row


def _record_relation_change(
    session: Session,
    actor: Identity,
    endpoint_rows,
    before_states: dict[int, TicketState],
    relation: TicketRelation,
    operation_id: UUID,
    audit_action: str,
) -> None:
    """관계 변경을 양 끝 티켓 이력과 감사 로그에 기록한다."""
    source_row, target_row = endpoint_rows
    source_ticket = source_row[0]
    target_ticket = target_row[0]
    for endpoint_row, counterpart_ticket in (
        (source_row, target_ticket),
        (target_row, source_ticket),
    ):
        endpoint_ticket = endpoint_row[0]
        after_state = _build_ticket_snapshot(
            session, endpoint_ticket, endpoint_row._mapping["parent_key"]
        )
        session.add(
            _build_ticket_change_history(
                endpoint_ticket,
                actor.id,
                HistoryEventType.RELATION_CHANGED,
                before_states[endpoint_ticket.id],
                after_state,
                ("relations",),
                operation_id=operation_id,
            )
        )
        record_ticket_audit_event(
            session,
            audit_action,
            actor.id,
            endpoint_ticket,
            operation_id=str(operation_id),
            relation_id=relation.id,
            relation_type=relation.relation_type,
            counterpart_ticket_key=counterpart_ticket.key,
            from_version=before_states[endpoint_ticket.id].version,
            to_version=after_state.version,
        )


def create_ticket_relation(
    session: Session,
    actor: Identity,
    project_key: str,
    ticket_key: str,
    payload: TicketRelationCreate,
) -> TicketDetailView:
    """현재 티켓에서 다른 티켓으로 관계를 생성한다."""
    with project_service.project_operation_context(
        session,
        actor,
        "ticket_relation_create",
        write_operation=True,
        conflict_code="ticket_relation_conflict",
        conflict_message="동일한 티켓 관계가 이미 존재합니다.",
        stale_code="ticket_version_conflict",
    ):
        project = _get_writable_project(session, actor, project_key)
        _require_active_project(project)
        current_row = _get_ticket_row(session, actor, project, ticket_key)
        current_ticket = current_row[0]
        _require_expected_version(current_ticket, payload.expected_version)
        target_row = repository.ticket_row(
            session,
            project.id,
            actor.id,
            payload.target_ticket_key,
            override=uses_system_administrator_override(project),
        )
        if target_row is None:
            raise AuthError(
                "invalid_relation_target", "같은 프로젝트의 유효한 티켓을 선택하세요."
            )
        target_ticket = target_row[0]
        if target_ticket.id == current_ticket.id:
            raise AuthError("self_ticket_relation", "티켓은 자기 자신과 관계를 맺을 수 없습니다.")
        _require_relation_ticket_editable(current_ticket)
        _require_relation_ticket_editable(target_ticket)

        if payload.relation_type == RelationType.RELATED:
            source_ticket, related_target_ticket = sorted(
                (current_ticket, target_ticket), key=lambda ticket: ticket.id
            )
        else:
            source_ticket = current_ticket
            related_target_ticket = target_ticket
        if repository.relation_exists(
            session,
            project.id,
            actor.id,
            source_ticket.id,
            related_target_ticket.id,
            payload.relation_type,
            override=uses_system_administrator_override(project),
        ):
            raise AuthError(
                "ticket_relation_conflict", "동일한 티켓 관계가 이미 존재합니다.", 409
            )

        endpoint_rows_by_id = {
            current_ticket.id: current_row,
            target_ticket.id: target_row,
        }
        source_row = endpoint_rows_by_id[source_ticket.id]
        target_endpoint_row = endpoint_rows_by_id[related_target_ticket.id]
        endpoint_rows = (source_row, target_endpoint_row)
        before_states = {
            endpoint_row[0].id: _build_ticket_snapshot(
                session, endpoint_row[0], endpoint_row._mapping["parent_key"]
            )
            for endpoint_row in endpoint_rows
        }
        relation = TicketRelation(
            project_id=project.id,
            source_ticket_id=source_ticket.id,
            target_ticket_id=related_target_ticket.id,
            relation_type=payload.relation_type,
            dependency_kind="FS"
            if payload.relation_type == RelationType.DEPENDS_ON
            else None,
            lag_days=0,
            created_by_id=actor.id,
        )
        session.add(relation)
        now = utc_now()
        source_ticket.updated_at = now
        related_target_ticket.updated_at = now
        session.flush()
        operation_id = uuid4()
        _record_relation_change(
            session,
            actor,
            endpoint_rows,
            before_states,
            relation,
            operation_id,
            "ticket.relation_created",
        )
        session.flush()
        result_row = _get_ticket_row(session, actor, project, current_ticket.key)
        result = build_ticket_detail_view(
            session,
            result_row,
            actor.id,
            override=uses_system_administrator_override(project),
        )
    logger.info(
        "ticket_relation_created actor_id=%s project_id=%s ticket_id=%s relation_id=%s",
        actor.id,
        result.project_id,
        result.id,
        relation.id,
    )
    return result


def delete_ticket_relation(
    session: Session,
    actor: Identity,
    project_key: str,
    ticket_key: str,
    relation_id: int,
    payload: TicketRelationDelete,
) -> TicketDetailView:
    """현재 티켓에 연결된 관계를 삭제한다."""
    with project_service.project_operation_context(
        session,
        actor,
        "ticket_relation_delete",
        write_operation=True,
        conflict_code="ticket_relation_conflict",
        conflict_message="티켓 관계가 변경되었습니다. 다시 확인하세요.",
        stale_code="ticket_version_conflict",
    ):
        project = _get_writable_project(session, actor, project_key)
        _require_active_project(project)
        current_row = _get_ticket_row(session, actor, project, ticket_key)
        current_ticket = current_row[0]
        _require_expected_version(current_ticket, payload.expected_version)
        relation = repository.ticket_relation(
            session,
            project.id,
            actor.id,
            current_ticket.id,
            relation_id,
            override=uses_system_administrator_override(project),
        )
        if relation is None:
            raise AuthError("ticket_relation_not_found", "티켓 관계를 찾을 수 없습니다.", 404)
        endpoint_rows = _relation_endpoint_rows(session, actor, project, relation)
        for endpoint_row in endpoint_rows:
            _require_relation_ticket_editable(endpoint_row[0])
        before_states = {
            endpoint_row[0].id: _build_ticket_snapshot(
                session, endpoint_row[0], endpoint_row._mapping["parent_key"]
            )
            for endpoint_row in endpoint_rows
        }
        relation_identifier = relation.id
        source_ticket = endpoint_rows[0][0]
        target_ticket = endpoint_rows[1][0]
        session.delete(relation)
        now = utc_now()
        source_ticket.updated_at = now
        target_ticket.updated_at = now
        session.flush()
        operation_id = uuid4()
        _record_relation_change(
            session,
            actor,
            endpoint_rows,
            before_states,
            relation,
            operation_id,
            "ticket.relation_deleted",
        )
        session.flush()
        result_row = _get_ticket_row(session, actor, project, current_ticket.key)
        result = build_ticket_detail_view(
            session,
            result_row,
            actor.id,
            override=uses_system_administrator_override(project),
        )
    logger.info(
        "ticket_relation_deleted actor_id=%s project_id=%s ticket_id=%s relation_id=%s",
        actor.id,
        result.project_id,
        result.id,
        relation_identifier,
    )
    return result


def get_ticket_creation_options(session: Session, actor: Identity, project_key: str):
    """티켓 생성에 필요한 담당자·상위 티켓 후보를 조회한다."""
    with project_service.project_operation_context(session, actor, "ticket_create_options"):
        project = _get_writable_project(session, actor, project_key)
        override = uses_system_administrator_override(project)
        return project, TicketCreateOptions(
            assignees=[
                TicketUserView(**row)
                for row in repository.assignees(session, project.id, actor.id, override=override)
            ],
            parents=[
                TicketParentView(**row)
                for row in repository.parent_candidates(
                    session, project.id, actor.id, override=override
                )
            ],
        )


def get_ticket_edit_options(session: Session, actor: Identity, project_key: str, ticket_key: str):
    """티켓 편집에 필요한 담당자·상위 티켓 후보를 조회한다."""
    with project_service.project_operation_context(session, actor, "ticket_edit_options"):
        project = _get_writable_project(session, actor, project_key)
        ticket_row = _get_ticket_row(session, actor, project, ticket_key)
        ticket = ticket_row[0]
        _require_active_project(project)
        if TicketStatus(ticket.status) in TERMINAL_STATUSES:
            raise AuthError(
                "terminal_ticket_locked", "완료·취소 티켓은 재개한 후 수정할 수 있습니다.", 409
            )
        allowed_parent_types = (
            (TicketType.EPIC,)
            if ticket.type == TicketType.TASK
            else ((TicketType.TASK,) if ticket.type == TicketType.SUBTASK else ())
        )
        override = uses_system_administrator_override(project)
        return project, build_ticket_view(ticket_row), TicketEditOptions(
            assignees=[
                TicketUserView(**candidate)
                for candidate in repository.assignees(
                    session, project.id, actor.id, override=override
                )
            ],
            parents=[
                TicketParentView(**candidate)
                for candidate in repository.parent_candidates(
                    session,
                    project.id,
                    actor.id,
                    override=override,
                    allowed_types=allowed_parent_types,
                    exclude_ticket_id=ticket.id,
                )
            ],
        )


def create_ticket(
    session: Session, actor: Identity, project_key: str, payload: TicketCreate
) -> TicketView:
    """티켓 생성을 처리한다."""
    with project_service.project_operation_context(
        session, actor, "ticket_create", write_operation=True
    ):
        project = _get_writable_project(session, actor, project_key)
        if not project.is_active:
            raise AuthError(
                "project_inactive", "비활성 프로젝트에는 티켓을 생성할 수 없습니다.", 409
            )
        override = uses_system_administrator_override(project)
        parent = None
        if payload.parent_key is not None:
            parent = repository.parent_ticket(
                session, project.id, actor.id, payload.parent_key, override=override
            )
            if parent is None:
                raise AuthError("invalid_parent", "유효한 상위 티켓을 선택하세요.")
        if payload.type == TicketType.TASK and parent and parent.type != TicketType.EPIC:
            raise AuthError("invalid_parent", "Task의 상위 티켓은 Epic이어야 합니다.")
        if payload.type == TicketType.SUBTASK and (
            parent is None or parent.type != TicketType.TASK
        ):
            raise AuthError("invalid_parent", "Subtask의 상위 티켓은 Task여야 합니다.")
        if payload.assignee_id is not None and not repository.assignee_is_active_member(
            session, project.id, payload.assignee_id
        ):
            raise AuthError("invalid_assignee", "활성 프로젝트 구성원을 담당자로 선택하세요.")
        number = repository.allocate_number(session, project.id)
        ticket = Ticket(
            project_id=project.id,
            number=number,
            key=f"{project.key}-{number}",
            type=payload.type,
            title=payload.title,
            description=payload.description,
            status=TicketStatus.TODO,
            priority=payload.priority,
            parent_id=parent.id if parent else None,
            creator_id=actor.id,
            assignee_id=payload.assignee_id,
            due_date=payload.due_date,
        )
        session.add(ticket)
        session.flush()
        session.add(
            _build_ticket_creation_history(ticket, parent.key if parent else None, actor.id)
        )
        record_ticket_audit_event(session, "ticket.created", actor.id, ticket)
        session.flush()
        row = repository.ticket_row(session, project.id, actor.id, ticket.key, override=override)
        if row is None:
            raise RuntimeError("Created ticket could not be read in its project scope")
        result = build_ticket_view(row)
    logger.info(
        "ticket_created actor_id=%s project_id=%s ticket_id=%s",
        actor.id,
        result.project_id,
        result.id,
    )
    return result


def update_ticket(
    session: Session, actor: Identity, project_key: str, ticket_key: str, payload: TicketUpdate
) -> TicketView:
    """티켓 수정을 처리한다."""
    changed_fields: list[str] = []
    with project_service.project_operation_context(
        session,
        actor,
        "ticket_update",
        write_operation=True,
        conflict_code="ticket_conflict",
        conflict_message="티켓 정보가 중복되거나 변경되었습니다. 다시 확인하세요.",
        stale_code="ticket_version_conflict",
    ):
        project = _get_writable_project(session, actor, project_key)
        _require_active_project(project)
        row = _get_ticket_row(session, actor, project, ticket_key)
        ticket = row[0]
        _require_expected_version(ticket, payload.expected_version)
        if TicketStatus(ticket.status) in TERMINAL_STATUSES:
            raise AuthError(
                "terminal_ticket_locked", "완료·취소 티켓은 재개한 후 수정할 수 있습니다.", 409
            )
        parent = _parent_for_update(session, actor, project, ticket, payload.parent_key)
        if (
            payload.assignee_id != ticket.assignee_id
            and payload.assignee_id is not None
            and not repository.assignee_is_active_member(session, project.id, payload.assignee_id)
        ):
            raise AuthError("invalid_assignee", "활성 프로젝트 구성원을 담당자로 선택하세요.")

        current_parent_key = row._mapping["parent_key"]
        desired = {
            "title": payload.title,
            "description": payload.description,
            "priority": payload.priority,
            "parent_key": parent.key if parent else None,
            "assignee_id": payload.assignee_id,
            "due_date": payload.due_date,
        }
        current = {
            "title": ticket.title,
            "description": ticket.description,
            "priority": Priority(ticket.priority),
            "parent_key": current_parent_key,
            "assignee_id": ticket.assignee_id,
            "due_date": ticket.due_date,
        }
        changed_fields = [field for field in desired if desired[field] != current[field]]
        if not changed_fields:
            return build_ticket_view(row)

        before = _build_ticket_snapshot(session, ticket, current_parent_key)
        ticket.title = payload.title
        ticket.description = payload.description
        ticket.priority = payload.priority
        ticket.parent_id = parent.id if parent else None
        ticket.assignee_id = payload.assignee_id
        ticket.due_date = payload.due_date
        ticket.updated_at = utc_now()
        session.flush()
        after = _build_ticket_snapshot(session, ticket, parent.key if parent else None)
        session.add(
            _build_ticket_change_history(
                ticket,
                actor.id,
                HistoryEventType.UPDATED,
                before,
                after,
                ("title", "description", "priority", "parent_key", "assignee_id", "due_date"),
            )
        )
        record_ticket_audit_event(
            session,
            "ticket.updated",
            actor.id,
            ticket,
            from_version=before.version,
            to_version=after.version,
            changed_fields=changed_fields,
        )
        session.flush()
        updated_row = _get_ticket_row(session, actor, project, ticket.key)
        result = build_ticket_view(updated_row)
    logger.info(
        "ticket_updated actor_id=%s project_id=%s ticket_id=%s version=%s fields=%s",
        actor.id,
        result.project_id,
        result.id,
        result.version,
        ",".join(changed_fields),
    )
    return result


def transition_ticket(
    session: Session, actor: Identity, project_key: str, ticket_key: str, payload: TicketTransition
) -> TicketView:
    """티켓 상태 전이를 처리한다."""
    with project_service.project_operation_context(
        session,
        actor,
        "ticket_transition",
        write_operation=True,
        conflict_code="ticket_conflict",
        conflict_message="티켓 상태가 변경되었습니다. 다시 확인하세요.",
        stale_code="ticket_version_conflict",
    ):
        project = _get_writable_project(session, actor, project_key)
        _require_active_project(project)
        row = _get_ticket_row(session, actor, project, ticket_key)
        ticket = row[0]
        _require_expected_version(ticket, payload.expected_version)
        current_status = TicketStatus(ticket.status)
        if payload.target_status not in get_allowed_transitions(current_status):
            raise AuthError(
                "invalid_status_transition", "현재 상태에서 요청한 상태로 변경할 수 없습니다.", 409
            )
        if payload.target_status == TicketStatus.DONE:
            if repository.incomplete_dependency_count(session, project.id, ticket.id):
                raise AuthError(
                    "incomplete_dependency",
                    "완료되지 않은 의존 대상이 있어 완료할 수 없습니다.",
                    409,
                )
            if (
                ticket.type == TicketType.EPIC
                and repository.incomplete_child_count(session, project.id, ticket.id)
                and not payload.confirm_incomplete_children
            ):
                raise AuthError(
                    "incomplete_child_confirmation_required",
                    "미완료 Task가 있습니다. 확인 후 Epic 완료를 다시 요청하세요.",
                    409,
                )

        current_parent_key = row._mapping["parent_key"]
        before = _build_ticket_snapshot(session, ticket, current_parent_key)
        now = utc_now()
        if current_status == TicketStatus.DONE:
            ticket.completed_at = None
        if current_status == TicketStatus.CANCELLED:
            ticket.cancelled_at = None
        if payload.target_status == TicketStatus.IN_PROGRESS and ticket.actual_started_at is None:
            ticket.actual_started_at = now
        if payload.target_status == TicketStatus.DONE:
            ticket.completed_at = now
        if payload.target_status == TicketStatus.CANCELLED:
            ticket.cancelled_at = now
        ticket.status = payload.target_status
        ticket.updated_at = now
        session.flush()
        after = _build_ticket_snapshot(session, ticket, current_parent_key)
        tracked_fields = (
            "status",
            "actual_started_at",
            "completed_at",
            "cancelled_at",
        )
        session.add(
            _build_ticket_change_history(
                ticket, actor.id, HistoryEventType.STATUS_CHANGED, before, after, tracked_fields
            )
        )
        record_ticket_audit_event(
            session,
            "ticket.status_changed",
            actor.id,
            ticket,
            from_version=before.version,
            to_version=after.version,
            from_status=before.status,
            to_status=after.status,
        )
        session.flush()
        updated_row = _get_ticket_row(session, actor, project, ticket.key)
        result = build_ticket_view(updated_row)
    logger.info(
        "ticket_status_changed actor_id=%s project_id=%s ticket_id=%s version=%s status=%s",
        actor.id,
        result.project_id,
        result.id,
        result.version,
        result.status,
    )
    return result
