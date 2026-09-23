import logging
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.types import utc_now
from app.domain.auth import AuthError, Identity
from app.domain.codes import HistoryEventType, Priority, ProjectRole, TicketStatus, TicketType
from app.models import AuditLog, Ticket, TicketHistory
from app.repositories import tickets as repository
from app.schemas.contracts import FieldChange, RelationSnapshot, TicketEvent, TicketState
from app.schemas.tickets import (
    BoardCard,
    BoardColumn,
    BoardDetachedGroup,
    BoardEpicGroup,
    BoardTask,
    BoardView,
    TicketCreate,
    TicketCreateOptions,
    TicketEditOptions,
    TicketPage,
    TicketParentView,
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
TERMINAL_STATUSES = {TicketStatus.DONE, TicketStatus.CANCELLED}
FSM_TRANSITIONS = {
    TicketStatus.TODO: (TicketStatus.IN_PROGRESS, TicketStatus.ON_HOLD, TicketStatus.CANCELLED),
    TicketStatus.IN_PROGRESS: (TicketStatus.DONE, TicketStatus.ON_HOLD, TicketStatus.CANCELLED),
    TicketStatus.ON_HOLD: (TicketStatus.TODO, TicketStatus.IN_PROGRESS, TicketStatus.CANCELLED),
    TicketStatus.DONE: (TicketStatus.IN_PROGRESS,),
    TicketStatus.CANCELLED: (TicketStatus.TODO,),
}


def audit(
    session: Session, action: str, actor_id: int, ticket: Ticket, **details: object
) -> None:
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


def _override(project) -> bool:
    return project.role is None and project.can_manage


def _user(id_: int | None, login_id: str | None, display_name: str | None):
    if id_ is None:
        return None
    return TicketUserView(id=id_, login_id=login_id or "", display_name=display_name or "")


def view(row) -> TicketView:
    ticket = row[0]
    mapping = row._mapping
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
        creator=_user(
            mapping["creator_id"],
            mapping["creator_login_id"],
            mapping["creator_display_name"],
        ),
        assignee=_user(
            mapping["assignee_id"],
            mapping["assignee_login_id"],
            mapping["assignee_display_name"],
        ),
        due_date=ticket.due_date,
        actual_started_at=ticket.actual_started_at,
        completed_at=ticket.completed_at,
        cancelled_at=ticket.cancelled_at,
        version=ticket.version,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


def _board_card(ticket: TicketView) -> BoardCard:
    return BoardCard(
        key=ticket.key,
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
    )


def _state(
    ticket: Ticket,
    parent_key: str | None,
    relations: list[RelationSnapshot] | None = None,
) -> TicketState:
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


def _creation_history(ticket: Ticket, parent_key: str | None, actor_id: int) -> TicketHistory:
    state = _state(ticket, parent_key)
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
        changes=[
            FieldChange(field="ticket", before=None, after=state.model_dump(mode="json"))
        ],
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


def _snapshot(session: Session, ticket: Ticket, parent_key: str | None) -> TicketState:
    relations = [
        RelationSnapshot(**row)
        for row in repository.relation_rows(session, ticket.project_id, ticket.id)
    ]
    return _state(ticket, parent_key, relations)


def _change_history(
    ticket: Ticket,
    actor_id: int,
    event_type: HistoryEventType,
    before: TicketState,
    after: TicketState,
    fields: tuple[str, ...],
) -> TicketHistory:
    before_data = before.model_dump(mode="json")
    after_data = after.model_dump(mode="json")
    changes = [
        FieldChange(field=field, before=before_data[field], after=after_data[field])
        for field in fields
        if before_data[field] != after_data[field]
    ]
    event = TicketEvent(
        event_key=uuid4(),
        operation_id=uuid4(),
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


def _project(session: Session, actor: Identity, project_key: str):
    return project_service.require_project_member(session, actor, project_key)


def allowed_transitions(status: TicketStatus | str) -> tuple[TicketStatus, ...]:
    return FSM_TRANSITIONS[TicketStatus(status)]


def can_edit(project, ticket: Ticket | TicketView, actor: Identity) -> bool:
    creator_id = ticket.creator_id if isinstance(ticket, Ticket) else ticket.creator.id
    assignee_id = ticket.assignee_id if isinstance(ticket, Ticket) else (
        ticket.assignee.id if ticket.assignee else None
    )
    return (
        creator_id == actor.id
        or assignee_id == actor.id
        or project.role == ProjectRole.ADMIN
        or project.can_manage
    )


def _require_edit_permission(
    session: Session, actor: Identity, project_key: str, project, ticket: Ticket
) -> None:
    if project.role is None and project.can_manage:
        project_service.require_project_admin(session, actor, project_key)
        return
    if ticket.creator_id == actor.id or ticket.assignee_id == actor.id:
        return
    if project.role == ProjectRole.ADMIN:
        return
    if project.can_manage:
        project_service.require_project_admin(session, actor, project_key)
        return
    raise AuthError("ticket_edit_forbidden", "이 티켓을 수정할 권한이 없습니다.", 403)


def _require_active_project(project) -> None:
    if not project.is_active:
        raise AuthError(
            "project_inactive", "비활성 프로젝트의 티켓은 변경할 수 없습니다.", 409
        )


def _require_expected_version(ticket: Ticket, expected_version: int) -> None:
    if ticket.version != expected_version:
        raise AuthError(
            "ticket_version_conflict",
            "다른 사용자가 먼저 변경했습니다. 최신 내용을 다시 불러오세요.",
            409,
        )


def _ticket_row(session: Session, actor: Identity, project, ticket_key: str):
    row = repository.ticket_row(
        session,
        project.id,
        actor.id,
        ticket_key.strip().upper(),
        override=_override(project),
    )
    if row is None:
        raise AuthError("ticket_not_found", "티켓을 찾을 수 없습니다.", 404)
    return row


def _parent_for_update(
    session: Session,
    actor: Identity,
    project,
    ticket: Ticket,
    parent_key: str | None,
) -> Ticket | None:
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
        override=_override(project),
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


def ticket_list(
    session: Session,
    actor: Identity,
    project_key: str,
    *,
    q: str = "",
    page: int = 1,
    page_size: int | None = None,
):
    size = page_size if page_size is not None else get_settings().pagination.default_size
    if len(q) > 200 or not 1 <= page <= 1_000_000 or size not in {10, 20, 50}:
        raise AuthError("invalid_filter", "검색 조건과 페이지 범위를 확인하세요.")
    with project_service.operation(session, actor, "ticket_list"):
        project = _project(session, actor, project_key)
        rows, total = repository.ticket_rows(
            session,
            project.id,
            actor.id,
            override=_override(project),
            query_text=q.strip(),
            page=page,
            page_size=size,
        )
        return project, TicketPage(
            tickets=[view(row) for row in rows], total=total, page=page, page_size=size
        )


def global_ticket_list(
    session: Session,
    actor: Identity,
    *,
    scope: str = "mine",
    status: str = "open",
    due: str = "all",
    q: str = "",
    page: int = 1,
    page_size: int | None = None,
):
    size = page_size if page_size is not None else get_settings().pagination.default_size
    if (
        scope not in {"mine", "created", "all"}
        or status not in {"open", "all"}
        or due not in {"all", "overdue", "this_week"}
        or len(q) > 200
        or not 1 <= page <= 1_000_000
        or size not in {10, 20, 50}
    ):
        raise AuthError("invalid_filter", "검색 조건과 페이지 범위를 확인하세요.")
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    week_end = today + timedelta(days=6 - today.weekday())
    with project_service.operation(session, actor, "global_ticket_list"):
        project_service.actor_is_admin(session, actor)
        rows, total = repository.filtered_ticket_rows(
            session,
            actor.id,
            scope_name=scope,
            status=status,
            due=due,
            today=today,
            week_end=week_end,
            query_text=q.strip(),
            page=page,
            page_size=size,
        )
        return TicketPage(
            tickets=[view(row) for row in rows], total=total, page=page, page_size=size
        )


def board(session: Session, actor: Identity, project_key: str):
    with project_service.operation(session, actor, "ticket_board"):
        project = _project(session, actor, project_key)
        rows = repository.board_rows(
            session, project.id, actor.id, override=_override(project)
        )
        indexed = {row[0].id: (row[0], view(row)) for row in rows}
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
                                card=_board_card(task_view),
                                subtasks=[
                                    _board_card(child_view)
                                    for child_row, child_view in children
                                    if child_row.status == ticket_status
                                ],
                            )
                        )
                    other_status_children = [
                        _board_card(child_view)
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
        return project, BoardView(groups=groups)


def ticket_detail(session: Session, actor: Identity, project_key: str, ticket_key: str):
    with project_service.operation(session, actor, "ticket_read"):
        project = _project(session, actor, project_key)
        row = _ticket_row(session, actor, project, ticket_key)
        return project, view(row)


def create_options(session: Session, actor: Identity, project_key: str):
    with project_service.operation(session, actor, "ticket_create_options"):
        project = _project(session, actor, project_key)
        override = _override(project)
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


def edit_options(
    session: Session, actor: Identity, project_key: str, ticket_key: str
):
    with project_service.operation(session, actor, "ticket_edit_options"):
        project = _project(session, actor, project_key)
        row = _ticket_row(session, actor, project, ticket_key)
        ticket = row[0]
        _require_edit_permission(session, actor, project_key, project, ticket)
        _require_active_project(project)
        if TicketStatus(ticket.status) in TERMINAL_STATUSES:
            raise AuthError(
                "terminal_ticket_locked",
                "완료·취소 티켓은 재개한 후 수정할 수 있습니다.",
                409,
            )
        allowed_parent_types = (
            (TicketType.EPIC,)
            if ticket.type == TicketType.TASK
            else ((TicketType.TASK,) if ticket.type == TicketType.SUBTASK else ())
        )
        override = _override(project)
        return project, view(row), TicketEditOptions(
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
    with project_service.operation(session, actor, "ticket_create", write=True):
        project = _project(session, actor, project_key)
        if not project.is_active:
            raise AuthError(
                "project_inactive", "비활성 프로젝트에는 티켓을 생성할 수 없습니다.", 409
            )
        override = _override(project)
        parent = None
        if payload.parent_key is not None:
            parent = repository.parent_ticket(
                session,
                project.id,
                actor.id,
                payload.parent_key,
                override=override,
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
        session.add(_creation_history(ticket, parent.key if parent else None, actor.id))
        audit(session, "ticket.created", actor.id, ticket)
        session.flush()
        row = repository.ticket_row(
            session, project.id, actor.id, ticket.key, override=override
        )
        if row is None:
            raise RuntimeError("Created ticket could not be read in its project scope")
        result = view(row)
    logger.info(
        "ticket_created actor_id=%s project_id=%s ticket_id=%s",
        actor.id,
        result.project_id,
        result.id,
    )
    return result


def update_ticket(
    session: Session,
    actor: Identity,
    project_key: str,
    ticket_key: str,
    payload: TicketUpdate,
) -> TicketView:
    changed_fields: list[str] = []
    with project_service.operation(
        session,
        actor,
        "ticket_update",
        write=True,
        conflict_code="ticket_conflict",
        conflict_message="티켓 정보가 중복되거나 변경되었습니다. 다시 확인하세요.",
        stale_code="ticket_version_conflict",
    ):
        project = _project(session, actor, project_key)
        _require_active_project(project)
        row = _ticket_row(session, actor, project, ticket_key)
        ticket = row[0]
        _require_edit_permission(session, actor, project_key, project, ticket)
        _require_expected_version(ticket, payload.expected_version)
        if TicketStatus(ticket.status) in TERMINAL_STATUSES:
            raise AuthError(
                "terminal_ticket_locked",
                "완료·취소 티켓은 재개한 후 수정할 수 있습니다.",
                409,
            )
        parent = _parent_for_update(
            session, actor, project, ticket, payload.parent_key
        )
        if (
            payload.assignee_id != ticket.assignee_id
            and payload.assignee_id is not None
            and not repository.assignee_is_active_member(
                session, project.id, payload.assignee_id
            )
        ):
            raise AuthError(
                "invalid_assignee", "활성 프로젝트 구성원을 담당자로 선택하세요."
            )

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
            return view(row)

        before = _snapshot(session, ticket, current_parent_key)
        ticket.title = payload.title
        ticket.description = payload.description
        ticket.priority = payload.priority
        ticket.parent_id = parent.id if parent else None
        ticket.assignee_id = payload.assignee_id
        ticket.due_date = payload.due_date
        ticket.updated_at = utc_now()
        session.flush()
        after = _snapshot(session, ticket, parent.key if parent else None)
        session.add(
            _change_history(
                ticket,
                actor.id,
                HistoryEventType.UPDATED,
                before,
                after,
                (
                    "title",
                    "description",
                    "priority",
                    "parent_key",
                    "assignee_id",
                    "due_date",
                ),
            )
        )
        audit(
            session,
            "ticket.updated",
            actor.id,
            ticket,
            from_version=before.version,
            to_version=after.version,
            changed_fields=changed_fields,
        )
        session.flush()
        updated_row = _ticket_row(session, actor, project, ticket.key)
        result = view(updated_row)
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
    session: Session,
    actor: Identity,
    project_key: str,
    ticket_key: str,
    payload: TicketTransition,
) -> TicketView:
    with project_service.operation(
        session,
        actor,
        "ticket_transition",
        write=True,
        conflict_code="ticket_conflict",
        conflict_message="티켓 상태가 변경되었습니다. 다시 확인하세요.",
        stale_code="ticket_version_conflict",
    ):
        project = _project(session, actor, project_key)
        _require_active_project(project)
        row = _ticket_row(session, actor, project, ticket_key)
        ticket = row[0]
        _require_edit_permission(session, actor, project_key, project, ticket)
        _require_expected_version(ticket, payload.expected_version)
        current_status = TicketStatus(ticket.status)
        if payload.target_status not in allowed_transitions(current_status):
            raise AuthError(
                "invalid_status_transition",
                "현재 상태에서 요청한 상태로 변경할 수 없습니다.",
                409,
            )
        if payload.target_status == TicketStatus.DONE:
            if repository.incomplete_dependency_count(
                session, project.id, ticket.id
            ):
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
        before = _snapshot(session, ticket, current_parent_key)
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
        after = _snapshot(session, ticket, current_parent_key)
        tracked_fields = (
            "status",
            "actual_started_at",
            "completed_at",
            "cancelled_at",
        )
        session.add(
            _change_history(
                ticket,
                actor.id,
                HistoryEventType.STATUS_CHANGED,
                before,
                after,
                tracked_fields,
            )
        )
        audit(
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
        updated_row = _ticket_row(session, actor, project, ticket.key)
        result = view(updated_row)
    logger.info(
        "ticket_status_changed actor_id=%s project_id=%s ticket_id=%s version=%s status=%s",
        actor.id,
        result.project_id,
        result.id,
        result.version,
        result.status,
    )
    return result
