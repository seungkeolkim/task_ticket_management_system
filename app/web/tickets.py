import json
from datetime import date, timedelta
from typing import Annotated, Literal
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.attachments import is_inline_image_media_type
from app.domain.auth import AuthError, Identity
from app.domain.codes import TicketType
from app.domain.rich_text import MAX_DOCUMENT_BYTES, empty_body_document
from app.schemas.comments import CommentCreate, CommentDelete, CommentUpdate
from app.schemas.contracts import TicketFilter
from app.schemas.tickets import (
    TicketCreate,
    TicketCreateOptions,
    TicketRelationCreate,
    TicketRelationDelete,
    TicketTransition,
    TicketTrashMove,
    TicketUpdate,
)
from app.services import attachments as attachment_service
from app.services import comments as comment_service
from app.services import personal_filters as personal_filter_service
from app.services import tickets as service
from app.storage.attachments import AttachmentStorage, get_attachment_storage
from app.web.attachment_responses import (
    build_attachment_download_response,
    build_attachment_inline_response,
)
from app.web.rendering import render
from app.web.security import require_web_user, verify_csrf

router = APIRouter(include_in_schema=False)
Database = Annotated[Session, Depends(get_db_session)]
Actor = Annotated[Identity, Depends(require_web_user)]
Storage = Annotated[AttachmentStorage, Depends(get_attachment_storage)]


def _inline_image_accept_value() -> str:
    """현재 설정에서 본문 image upload에 사용할 확장자 accept 값을 반환한다."""
    attachment_settings = get_settings().attachments
    image_extensions = [
        extension
        for extension in attachment_settings.allowed_extensions
        if any(
            is_inline_image_media_type(media_type)
            for media_type in attachment_settings.allowed_media_types.get(extension, [])
        )
    ]
    return ",".join(f".{extension}" for extension in image_extensions)


def _parse_description_document(raw_document: str) -> object:
    """HTML form의 hidden JSON payload를 Python 객체로 변환한다."""
    if not raw_document.strip():
        return empty_body_document()
    if len(raw_document.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise ValueError("설명 본문 크기가 허용 범위를 초과했습니다.")
    try:
        return json.loads(raw_document)
    except json.JSONDecodeError as error:
        raise ValueError("설명 본문 JSON 형식이 올바르지 않습니다.") from error


def _parse_comment_document(raw_document: str) -> object:
    """댓글 form의 hidden JSON payload를 Python 객체로 변환한다."""
    if not raw_document.strip():
        return empty_body_document()
    if len(raw_document.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise ValueError("댓글 본문 크기가 허용 범위를 초과했습니다.")
    try:
        return json.loads(raw_document)
    except json.JSONDecodeError as error:
        raise ValueError("댓글 본문 JSON 형식이 올바르지 않습니다.") from error


def _project_ticket_filter_query(ticket_filter: TicketFilter) -> list[tuple[str, str | int]]:
    """검증된 filter를 반복 값을 보존하는 URL query 항목으로 변환한다."""
    query_items: list[tuple[str, str | int]] = []
    if ticket_filter.query:
        query_items.append(("q", ticket_filter.query))
    query_items.extend(("type", item.value) for item in ticket_filter.types)
    query_items.extend(("status", item.value) for item in ticket_filter.statuses)
    query_items.extend(("priority", item.value) for item in ticket_filter.priorities)
    if ticket_filter.epic_id is not None:
        query_items.append(("epic_id", ticket_filter.epic_id))
    if ticket_filter.parent_id is not None:
        query_items.append(("parent_id", ticket_filter.parent_id))
    query_items.extend(("creator_id", item) for item in ticket_filter.creator_ids)
    query_items.extend(("assignee_id", item) for item in ticket_filter.assignee_ids)
    if ticket_filter.unassigned:
        query_items.append(("unassigned", "true"))
    timezone = ZoneInfo("Asia/Seoul")
    if ticket_filter.created_from is not None:
        created_from = ticket_filter.created_from.astimezone(timezone).date()
        query_items.append(("created_from", created_from.isoformat()))
    if ticket_filter.created_before is not None:
        created_through = (
            ticket_filter.created_before.astimezone(timezone).date() - timedelta(days=1)
        )
        query_items.append(("created_through", created_through.isoformat()))
    if ticket_filter.updated_from is not None:
        updated_from = ticket_filter.updated_from.astimezone(timezone).date()
        query_items.append(("updated_from", updated_from.isoformat()))
    if ticket_filter.updated_before is not None:
        updated_through = (
            ticket_filter.updated_before.astimezone(timezone).date() - timedelta(days=1)
        )
        query_items.append(("updated_through", updated_through.isoformat()))
    if ticket_filter.due_from is not None:
        query_items.append(("due_from", ticket_filter.due_from.isoformat()))
    if ticket_filter.due_through is not None:
        query_items.append(("due_through", ticket_filter.due_through.isoformat()))
    query_items.extend(
        (
            ("sort_by", ticket_filter.sort_by),
            ("sort_direction", ticket_filter.sort_direction),
            ("page_size", ticket_filter.page_size),
        )
    )
    return query_items


def _optional_positive_integer(raw_value: str) -> int | None:
    """빈 HTML query 값 또는 양의 정수를 안전하게 변환한다."""
    if not raw_value:
        return None
    try:
        value = int(raw_value)
    except ValueError as error:
        raise AuthError("invalid_filter", "검색 조건과 페이지 범위를 확인하세요.") from error
    if value <= 0:
        raise AuthError("invalid_filter", "검색 조건과 페이지 범위를 확인하세요.")
    return value


def _positive_integer_values(raw_values: list[str] | None) -> list[int]:
    """HTML query의 비어 있지 않은 양의 정수 목록을 변환한다."""
    return [
        value
        for raw_value in (raw_values or [])
        if (value := _optional_positive_integer(raw_value)) is not None
    ]


def _optional_date(raw_value: str) -> date | None:
    """빈 HTML date query 값 또는 ISO 날짜를 안전하게 변환한다."""
    if not raw_value:
        return None
    try:
        return date.fromisoformat(raw_value)
    except ValueError as error:
        raise AuthError("invalid_filter", "검색 조건과 페이지 범위를 확인하세요.") from error


def _parse_ticket_properties(
    labels: str | None, custom_fields: str | None, properties_present: bool = False
) -> dict[str, object]:
    """HTML 속성 입력을 변환하며 생략된 속성은 기존 API와 같이 보존한다."""
    properties: dict[str, object] = {}
    if properties_present:
        labels = labels or ""
        custom_fields = custom_fields or "[]"
    if labels is not None:
        if len(labels) > 4096:
            raise ValueError("Label 입력이 너무 깁니다.")
        properties["labels"] = [label for label in labels.splitlines() if label.strip()]
    if custom_fields is not None:
        if len(custom_fields) > 1000000:
            raise ValueError("추가 필드 입력이 너무 큽니다.")
        try:
            properties["custom_fields"] = json.loads(custom_fields or "[]")
        except (ValueError, RecursionError) as error:
            raise ValueError("추가 필드 입력을 확인하세요.") from error
    return properties


def _ticket_form_error_message(
    error: ValidationError | AuthError | ValueError, default_message: str
) -> str:
    """티켓 form 검증 예외를 입력 원문이 포함되지 않은 사용자 메시지로 변환한다."""
    if isinstance(error, AuthError):
        return error.message
    if isinstance(error, ValidationError):
        for validation_error in error.errors():
            if any(
                name in validation_error.get("loc", ()) for name in ("labels", "custom_fields")
            ):
                return (
                    "Label은 최대 30개·각 64자입니다. "
                    "추가 필드는 최대 30개·이름 100자·값 10,000자입니다. "
                    "빈 이름, 중복 필드 이름, 잘못된 ID 또는 Text 이외 타입을 확인하세요."
                )
        for validation_error in error.errors():
            if "description_document" not in validation_error.get("loc", ()):
                continue
            message = str(validation_error.get("msg", ""))
            return message.removeprefix("Value error, ") or default_message
        return default_message
    return str(error)


def _comment_form_error_message(
    error: ValidationError | AuthError | ValueError,
    default_message: str,
) -> str:
    """댓글 form 예외를 본문 원문이 없는 사용자 메시지로 변환한다."""
    if isinstance(error, AuthError):
        return error.message
    if isinstance(error, ValidationError):
        for validation_error in error.errors():
            if "body_document" not in validation_error.get("loc", ()):
                continue
            message = str(validation_error.get("msg", ""))
            return message.removeprefix("Value error, ") or default_message
        return default_message
    return str(error)


@router.get("/tickets")
def global_ticket_list_page(
    request: Request,
    session: Database,
    actor: Actor,
    scope: str = "mine",
    status: str = "open",
    due: str = "all",
    search_query: Annotated[str, Query(alias="q")] = "",
    page: int = 1,
    page_size: int | None = None,
):
    """전체 티켓 목록 화면을 렌더링한다."""
    result = service.list_global_tickets(
        session,
        actor,
        scope=scope,
        status=status,
        due=due,
        search_query=search_query,
        page=page,
        page_size=page_size,
    )
    query = {
        "scope": scope,
        "status": status,
        "due": due,
        "q": search_query,
        "page_size": result.page_size,
    }
    return render(
        request,
        "global_ticket_list.html",
        live_page=True,
        page_title="내 티켓",
        active="tickets",
        result=result,
        filters=query,
        previous_url="/tickets?" + urlencode(query | {"page": page - 1}),
        next_url="/tickets?" + urlencode(query | {"page": page + 1}),
    )


def project_ticket_filter_parameters(
    search_query: Annotated[str, Query(alias="q")] = "",
    types: Annotated[list[str] | None, Query(alias="type")] = None,
    statuses: Annotated[list[str] | None, Query(alias="status")] = None,
    priorities: Annotated[list[str] | None, Query(alias="priority")] = None,
    epic_id: str = "",
    parent_id: str = "",
    creator_ids: Annotated[list[str] | None, Query(alias="creator_id")] = None,
    assignee_ids: Annotated[list[str] | None, Query(alias="assignee_id")] = None,
    unassigned: bool = False,
    created_from: str = "",
    created_through: str = "",
    updated_from: str = "",
    updated_through: str = "",
    due_from: str = "",
    due_through: str = "",
    sort_by: str = "updated_at",
    sort_direction: str = "desc",
    page_size: int | None = None,
) -> TicketFilter:
    """빈 HTML 입력을 처리하고 목록·칸반의 공통 filter를 구성한다."""
    return service.build_project_ticket_filter(
        search_query=search_query,
        types=types,
        statuses=statuses,
        priorities=priorities,
        epic_id=_optional_positive_integer(epic_id),
        parent_id=_optional_positive_integer(parent_id),
        creator_ids=_positive_integer_values(creator_ids),
        assignee_ids=_positive_integer_values(assignee_ids),
        unassigned=unassigned,
        created_from=_optional_date(created_from),
        created_through=_optional_date(created_through),
        updated_from=_optional_date(updated_from),
        updated_through=_optional_date(updated_through),
        due_from=_optional_date(due_from),
        due_through=_optional_date(due_through),
        sort_by=sort_by,
        sort_direction=sort_direction,
        page_size=page_size,
    )


@router.get("/projects/{project_key}/personal-filters/{filter_id}/apply")
def apply_personal_filter_page(
    project_key: str, filter_id: int, session: Database, actor: Actor,
    view: Literal["tickets", "board"] = "tickets",
):
    """저장 조건을 재검증한 뒤 지정 화면의 첫 페이지에 적용한다."""
    personal_filter = personal_filter_service.get_personal_filter(
        session, actor, project_key, filter_id
    )
    query_items = _project_ticket_filter_query(personal_filter.definition)
    return RedirectResponse(
        f"/projects/{project_key}/{view}?" + urlencode(query_items), status_code=303
    )


@router.get("/projects/{project_key}/board")
def project_ticket_board_page(
    project_key: str,
    request: Request,
    session: Database,
    actor: Actor,
    ticket_filter: Annotated[TicketFilter, Depends(project_ticket_filter_parameters)],
):
    """프로젝트 티켓 보드 화면을 렌더링한다."""
    project, board = service.build_ticket_board(
        session, actor, project_key, ticket_filter=ticket_filter
    )
    filter_options = service.get_project_ticket_filter_options(session, actor, project_key)
    query_items = _project_ticket_filter_query(ticket_filter)
    return render(
        request,
        "board.html",
        live_page=True,
        page_title=f"칸반 · {project.key}",
        active="board",
        project=project,
        board=board,
        filters=ticket_filter,
        personal_filters=personal_filter_service.list_personal_filters(session, actor, project_key),
        q=ticket_filter.query,
        filter_options=filter_options,
        filter_dates=dict(query_items),
        filter_action=f"/projects/{project.key}/board",
        is_board_filter=True,
        ticket_list_url=f"/projects/{project.key}/tickets?" + urlencode(query_items),
    )


def _ticket_create_prefill_values(
    ticket_type: str,
    parent_key: str,
    options: TicketCreateOptions,
) -> dict[str, str]:
    """검증된 query 값으로 새 티켓 form의 유형과 상위 티켓 초기값을 구성한다."""
    if not ticket_type and not parent_key:
        return {}
    try:
        selected_ticket_type = TicketType(ticket_type)
    except ValueError as error:
        raise AuthError(
            "invalid_ticket_prefill",
            "새 티켓의 유형과 상위 티켓을 확인하세요.",
            400,
        ) from error

    selected_parent = next(
        (candidate for candidate in options.parents if candidate.key == parent_key),
        None,
    )
    expected_parent_type = {
        TicketType.EPIC: None,
        TicketType.TASK: TicketType.EPIC,
        TicketType.SUBTASK: TicketType.TASK,
    }[selected_ticket_type]
    if (
        (selected_ticket_type == TicketType.EPIC and parent_key)
        or (selected_ticket_type == TicketType.SUBTASK and not parent_key)
        or (parent_key and selected_parent is None)
        or (selected_parent is not None and selected_parent.type != expected_parent_type)
    ):
        raise AuthError(
            "invalid_ticket_prefill",
            "새 티켓의 유형과 상위 티켓을 확인하세요.",
            400,
        )
    return {"type": selected_ticket_type.value, "parent_key": parent_key}


def _render_ticket_create_page(
    request,
    session,
    actor,
    project_key,
    prefill_ticket_type: str = "",
    prefill_parent_key: str = "",
    **context,
):
    """티켓 create 화면 렌더링한다."""
    project, options = service.get_ticket_creation_options(session, actor, project_key)
    if "values" not in context:
        context["values"] = _ticket_create_prefill_values(
            prefill_ticket_type,
            prefill_parent_key,
            options,
        )
    return render(
        request,
        "ticket_form.html",
        live_page=True,
        page_title=f"새 티켓 · {project.key}",
        active="tickets",
        project=project,
        options=options,
        mode="create",
        **context,
    )


def _render_ticket_edit_page(request, session, actor, project_key, ticket_key, **context):
    """티켓 edit 화면 렌더링한다."""
    project, ticket, options = service.get_ticket_edit_options(
        session, actor, project_key, ticket_key
    )
    values = context.pop(
        "values",
        {
            "title": ticket.title,
            "description_document_json": json.dumps(
                ticket.description_document, ensure_ascii=False, separators=(",", ":")
            ),
            "priority": ticket.priority.value,
            "parent_key": ticket.parent.key if ticket.parent else "",
            "assignee_id": str(ticket.assignee.id) if ticket.assignee else "",
            "due_date": ticket.due_date.isoformat() if ticket.due_date else "",
            "labels_text": "\n".join(ticket.labels),
            "custom_fields_json": json.dumps(
                [field.model_dump(mode="json") for field in ticket.custom_fields],
                ensure_ascii=False,
            ),
            "expected_version": str(ticket.version),
        },
    )
    values.setdefault("labels_text", "\n".join(ticket.labels))
    values.setdefault(
        "custom_fields_json",
        json.dumps(
            [field.model_dump(mode="json") for field in ticket.custom_fields], ensure_ascii=False
        ),
    )
    attachment_image_accept = _inline_image_accept_value()
    return render(
        request,
        "ticket_form.html",
        live_page=True,
        page_title=f"{ticket.key} 편집",
        active="tickets",
        project=project,
        ticket=ticket,
        options=options,
        mode="edit",
        values=values,
        attachment_image_upload_url=(
            f"/api/projects/{project.key}/tickets/{ticket.key}/attachments"
            if attachment_image_accept
            else ""
        ),
        attachment_image_ticket_version=ticket.version,
        attachment_image_accept=attachment_image_accept,
        **context,
    )


def _render_ticket_detail_page(request, session, actor, project_key, ticket_key, **context):
    """티켓 상세 화면 렌더링한다."""
    project, ticket = service.get_ticket_detail(session, actor, project_key, ticket_key)
    _, _, comments = comment_service.list_ticket_comments(
        session,
        actor,
        project_key,
        ticket_key,
    )
    _, _, attachments = attachment_service.list_ticket_attachments(
        session,
        actor,
        project_key,
        ticket_key,
    )
    edit_comment_id = context.pop("edit_comment_id", None)
    reply_comment_id = context.pop("reply_comment_id", None)
    selected_comment = None
    if edit_comment_id is not None:
        selected_comment = next(
            (comment for comment in comments if comment.id == edit_comment_id),
            None,
        )
        if selected_comment is None or selected_comment.is_deleted:
            raise AuthError("comment_not_found", "댓글을 찾을 수 없습니다.", 404)
    reply_parent_comment = None
    if reply_comment_id is not None:
        reply_parent_comment = next(
            (comment for comment in comments if comment.id == reply_comment_id),
            None,
        )
        if (
            reply_parent_comment is None
            or reply_parent_comment.is_deleted
            or reply_parent_comment.depth != 0
        ):
            raise AuthError("parent_comment_not_found", "답글 대상 댓글을 찾을 수 없습니다.", 404)
    comment_form_values = context.pop("comment_form_values", None)
    if selected_comment is not None and comment_form_values is None:
        comment_form_values = {
            "body_document_json": json.dumps(
                selected_comment.body_document,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "expected_version": str(selected_comment.version),
        }
    transitions = [
        (status, service.STATUS_LABELS[status][0])
        for status in service.get_allowed_transitions(ticket.status)
    ]
    can_manage_attachments = attachment_service.can_manage_attachments(project)
    attachment_image_accept = _inline_image_accept_value()
    return render(
        request,
        "ticket_detail.html",
        live_page=True,
        page_title=f"{ticket.key} · {ticket.title}",
        active="tickets",
        project=project,
        ticket=ticket,
        can_edit=service.can_edit_ticket(project, ticket, actor),
        can_manage_comments=comment_service.can_manage_comments(project),
        can_manage_attachments=can_manage_attachments,
        attachments=attachments,
        attachment_accept=",".join(
            f".{extension}" for extension in get_settings().attachments.allowed_extensions
        ),
        attachment_max_size_mb=get_settings().attachments.max_file_size_mb,
        attachment_image_upload_url=(
            f"/api/projects/{project.key}/tickets/{ticket.key}/attachments"
            if can_manage_attachments and attachment_image_accept
            else ""
        ),
        attachment_image_ticket_version=ticket.version,
        attachment_image_accept=attachment_image_accept,
        comments=comments,
        selected_comment=selected_comment,
        reply_parent_comment=reply_parent_comment,
        comment_form_values=comment_form_values,
        transitions=transitions,
        **context,
    )


@router.get("/attachments/{attachment_id}")
def display_inline_attachment_image(
    attachment_id: int,
    session: Database,
    actor: Actor,
    storage: Storage,
):
    """본문 image node가 참조하는 권한 보호 raster image를 표시한다."""
    download = attachment_service.open_inline_attachment_image(
        session,
        actor,
        attachment_id,
        storage,
    )
    return build_attachment_inline_response(download)


@router.get("/projects/{project_key}/tickets")
def project_ticket_list_page(
    project_key: str,
    request: Request,
    session: Database,
    actor: Actor,
    ticket_filter: Annotated[TicketFilter, Depends(project_ticket_filter_parameters)],
    page: int = 1,
    selected: str | None = None,
    created: bool = False,
):
    """프로젝트 티켓 목록 화면을 렌더링한다."""
    project, result, filter_options = service.list_project_tickets(
        session,
        actor,
        project_key,
        ticket_filter=ticket_filter,
        page=page,
        include_filter_options=True,
    )
    selected_ticket = None
    if selected:
        _, selected_ticket = service.get_ticket_detail(session, actor, project_key, selected)
    query_items = _project_ticket_filter_query(ticket_filter)
    current_page_url = f"/projects/{project.key}/tickets?" + urlencode(
        query_items + [("page", page)], doseq=True
    )
    return render(
        request,
        "ticket_list.html",
        live_page=True,
        page_title=f"티켓 · {project.key}",
        active="tickets",
        project=project,
        result=result,
        q=ticket_filter.query,
        filters=ticket_filter,
        personal_filters=personal_filter_service.list_personal_filters(session, actor, project_key),
        filter_options=filter_options,
        filter_dates=dict(query_items),
        filter_action=f"/projects/{project.key}/tickets",
        board_url=f"/projects/{project.key}/board?" + urlencode(query_items),
        selected_ticket=selected_ticket,
        created=created,
        current_page_url=current_page_url,
        previous_url=f"/projects/{project.key}/tickets?"
        + urlencode(query_items + [("page", page - 1)], doseq=True),
        next_url=f"/projects/{project.key}/tickets?"
        + urlencode(query_items + [("page", page + 1)], doseq=True),
    )


@router.get("/projects/{project_key}/tickets/new")
def new_ticket_page(
    project_key: str,
    request: Request,
    session: Database,
    actor: Actor,
    ticket_type: Annotated[str, Query(alias="type", max_length=16)] = "",
    parent_key: Annotated[str, Query(max_length=64)] = "",
):
    """티켓 화면 새 값을 생성한다."""
    return _render_ticket_create_page(
        request,
        session,
        actor,
        project_key,
        prefill_ticket_type=ticket_type,
        prefill_parent_key=parent_key,
    )


@router.get("/projects/{project_key}/tickets/{ticket_key}/edit")
def edit_ticket_page(
    project_key: str, ticket_key: str, request: Request, session: Database, actor: Actor
):
    """티켓 편집 화면을 렌더링한다."""
    return _render_ticket_edit_page(request, session, actor, project_key, ticket_key)


@router.post("/projects/{project_key}/tickets")
def create_ticket_submit(
    project_key: str,
    request: Request,
    session: Database,
    actor: Actor,
    type: Annotated[str, Form()] = "TASK",
    title: Annotated[str, Form()] = "",
    description_document: Annotated[str, Form()] = "",
    priority: Annotated[str, Form()] = "MAJOR",
    parent_key: Annotated[str, Form()] = "",
    assignee_id: Annotated[str, Form()] = "",
    due_date: Annotated[str, Form()] = "",
    labels: Annotated[str | None, Form()] = None,
    custom_fields: Annotated[str | None, Form()] = None,
    properties_present: Annotated[bool, Form()] = False,
    csrf_token: Annotated[str, Form()] = "",
):
    """티켓 submit 생성을 처리한다."""
    verify_csrf(request, csrf_token, actor, get_settings())
    values = {
        "type": type[:16],
        "title": title[:200],
        "description_document_json": description_document[:MAX_DOCUMENT_BYTES],
        "priority": priority[:16],
        "parent_key": parent_key[:64],
        "assignee_id": assignee_id[:20],
        "due_date": due_date[:10],
        "labels_text": (labels or "")[:4096],
        "custom_fields_json": (custom_fields or "[]")[:1000000],
    }
    try:
        payload = TicketCreate(
            **_parse_ticket_properties(labels, custom_fields, properties_present),
            type=type,
            title=title,
            description_document=_parse_description_document(description_document),
            priority=priority,
            parent_key=parent_key,
            assignee_id=assignee_id or None,
            due_date=due_date or None,
        )
        ticket = service.create_ticket(session, actor, project_key, payload)
    except (ValidationError, AuthError, ValueError) as error:
        if isinstance(error, AuthError) and error.status_code in {401, 403, 404}:
            raise
        return _render_ticket_create_page(
            request,
            session,
            actor,
            project_key,
            values=values,
            error=_ticket_form_error_message(
                error,
                "티켓 유형, 제목, 설명, 상위 티켓과 담당자를 확인하세요.",
            ),
            status_code=error.status_code if isinstance(error, AuthError) else 422,
        )
    return RedirectResponse(
        f"/projects/{project_key}/tickets/{ticket.key}?created=1", status_code=303
    )


@router.post("/projects/{project_key}/tickets/{ticket_key}")
def update_ticket_submit(
    project_key: str,
    ticket_key: str,
    request: Request,
    session: Database,
    actor: Actor,
    title: Annotated[str, Form()] = "",
    description_document: Annotated[str, Form()] = "",
    priority: Annotated[str, Form()] = "MAJOR",
    parent_key: Annotated[str, Form()] = "",
    assignee_id: Annotated[str, Form()] = "",
    due_date: Annotated[str, Form()] = "",
    labels: Annotated[str | None, Form()] = None,
    custom_fields: Annotated[str | None, Form()] = None,
    properties_present: Annotated[bool, Form()] = False,
    expected_version: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """티켓 submit 수정을 처리한다."""
    verify_csrf(request, csrf_token, actor, get_settings())
    values = {
        "title": title[:200],
        "description_document_json": description_document[:MAX_DOCUMENT_BYTES],
        "priority": priority[:16],
        "parent_key": parent_key[:64],
        "assignee_id": assignee_id[:20],
        "due_date": due_date[:10],
        "expected_version": expected_version[:20],
        "labels_text": (labels or "")[:4096],
        "custom_fields_json": (custom_fields or "[]")[:1000000],
    }
    if not properties_present and labels is None:
        values.pop("labels_text")
    if not properties_present and custom_fields is None:
        values.pop("custom_fields_json")
    try:
        payload = TicketUpdate(
            **_parse_ticket_properties(labels, custom_fields, properties_present),
            title=title,
            description_document=_parse_description_document(description_document),
            priority=priority,
            parent_key=parent_key,
            assignee_id=assignee_id or None,
            due_date=due_date or None,
            expected_version=expected_version,
        )
        ticket = service.update_ticket(session, actor, project_key, ticket_key, payload)
    except (ValidationError, AuthError, ValueError) as error:
        if isinstance(error, AuthError) and error.status_code in {401, 403, 404}:
            raise
        conflict = (
            isinstance(error, AuthError)
            and error.code == "ticket_version_conflict"
        )
        return _render_ticket_edit_page(
            request,
            session,
            actor,
            project_key,
            ticket_key,
            values=values,
            error=_ticket_form_error_message(
                error,
                "제목, 설명, 상위 티켓과 담당자를 확인하세요.",
            ),
            conflict=conflict,
            status_code=error.status_code if isinstance(error, AuthError) else 422,
        )
    return RedirectResponse(
        f"/projects/{project_key}/tickets/{ticket.key}?updated=1", status_code=303
    )


@router.post("/projects/{project_key}/tickets/{ticket_key}/transition")
def transition_ticket_submit(
    project_key: str,
    ticket_key: str,
    request: Request,
    session: Database,
    actor: Actor,
    target_status: Annotated[str, Form()] = "",
    expected_version: Annotated[str, Form()] = "",
    confirm_incomplete_children: Annotated[bool, Form()] = False,
    csrf_token: Annotated[str, Form()] = "",
):
    """티켓 submit 상태 전이를 처리한다."""
    verify_csrf(request, csrf_token, actor, get_settings())
    try:
        payload = TicketTransition(
            target_status=target_status,
            expected_version=expected_version,
            confirm_incomplete_children=confirm_incomplete_children,
        )
        ticket = service.transition_ticket(session, actor, project_key, ticket_key, payload)
    except (ValidationError, AuthError) as error:
        if isinstance(error, AuthError) and error.status_code in {401, 403, 404}:
            raise
        confirmation = (
            isinstance(error, AuthError)
            and error.code == "incomplete_child_confirmation_required"
        )
        return _render_ticket_detail_page(
            request,
            session,
            actor,
            project_key,
            ticket_key,
            error=error.message if isinstance(error, AuthError) else "상태 변경 요청을 확인하세요.",
            confirmation_status=target_status if confirmation else None,
            status_code=error.status_code if isinstance(error, AuthError) else 422,
        )
    return RedirectResponse(
        f"/projects/{project_key}/tickets/{ticket.key}?transitioned=1", status_code=303
    )


@router.post("/projects/{project_key}/tickets/{ticket_key}/relations")
def create_ticket_relation_submit(
    project_key: str,
    ticket_key: str,
    request: Request,
    session: Database,
    actor: Actor,
    relation_type: Annotated[str, Form()] = "RELATED",
    target_ticket_key: Annotated[str, Form()] = "",
    expected_version: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """티켓 관계 form 생성을 처리한다."""
    verify_csrf(request, csrf_token, actor, get_settings())
    relation_values = {
        "relation_type": relation_type[:24],
        "target_ticket_key": target_ticket_key[:64],
    }
    try:
        payload = TicketRelationCreate(
            relation_type=relation_type,
            target_ticket_key=target_ticket_key,
            expected_version=expected_version,
        )
        ticket = service.create_ticket_relation(
            session, actor, project_key, ticket_key, payload
        )
    except (ValidationError, AuthError) as error:
        if isinstance(error, AuthError) and error.status_code in {401, 403, 404}:
            raise
        return _render_ticket_detail_page(
            request,
            session,
            actor,
            project_key,
            ticket_key,
            relation_values=relation_values,
            error=error.message
            if isinstance(error, AuthError)
            else "관계 유형, 대상 티켓과 현재 버전을 확인하세요.",
            status_code=error.status_code if isinstance(error, AuthError) else 422,
        )
    return RedirectResponse(
        f"/projects/{project_key}/tickets/{ticket.key}?relation_created=1", status_code=303
    )


@router.post("/projects/{project_key}/tickets/{ticket_key}/relations/{relation_id}/delete")
def delete_ticket_relation_submit(
    project_key: str,
    ticket_key: str,
    relation_id: int,
    request: Request,
    session: Database,
    actor: Actor,
    expected_version: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """티켓 관계 form 삭제를 처리한다."""
    verify_csrf(request, csrf_token, actor, get_settings())
    try:
        payload = TicketRelationDelete(expected_version=expected_version)
        ticket = service.delete_ticket_relation(
            session, actor, project_key, ticket_key, relation_id, payload
        )
    except (ValidationError, AuthError) as error:
        if isinstance(error, AuthError) and error.status_code in {401, 403, 404}:
            raise
        return _render_ticket_detail_page(
            request,
            session,
            actor,
            project_key,
            ticket_key,
            error=error.message
            if isinstance(error, AuthError)
            else "관계 삭제 요청과 현재 버전을 확인하세요.",
            status_code=error.status_code if isinstance(error, AuthError) else 422,
        )
    return RedirectResponse(
        f"/projects/{project_key}/tickets/{ticket.key}?relation_deleted=1", status_code=303
    )


@router.post("/projects/{project_key}/tickets/{ticket_key}/trash")
def move_ticket_to_trash_submit(
    project_key: str,
    ticket_key: str,
    request: Request,
    session: Database,
    actor: Actor,
    expected_version: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """티켓 계층의 form 휴지통 이동을 처리한다."""
    verify_csrf(request, csrf_token, actor, get_settings())
    try:
        payload = TicketTrashMove(expected_version=expected_version)
        batch = service.move_ticket_to_trash(session, actor, project_key, ticket_key, payload)
    except (ValidationError, AuthError) as error:
        if isinstance(error, AuthError) and error.status_code in {401, 403, 404}:
            raise
        return _render_ticket_detail_page(
            request,
            session,
            actor,
            project_key,
            ticket_key,
            error=error.message
            if isinstance(error, AuthError)
            else "휴지통 이동 요청과 현재 버전을 확인하세요.",
            status_code=error.status_code if isinstance(error, AuthError) else 422,
        )
    return RedirectResponse(
        f"/projects/{project_key}/trash?deleted={batch.root_ticket_key}", status_code=303
    )


@router.post("/projects/{project_key}/tickets/{ticket_key}/comments")
def create_comment_submit(
    project_key: str,
    ticket_key: str,
    request: Request,
    session: Database,
    actor: Actor,
    body_document: Annotated[str, Form()] = "",
    parent_comment_id: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """티켓 댓글 form 생성을 처리한다."""
    verify_csrf(request, csrf_token, actor, get_settings())
    comment_form_values = {
        "body_document_json": body_document[:MAX_DOCUMENT_BYTES],
        "parent_comment_id": parent_comment_id[:20],
    }
    try:
        payload = CommentCreate(
            body_document=_parse_comment_document(body_document),
            parent_comment_id=parent_comment_id or None,
        )
        created_comment = comment_service.create_comment(
            session,
            actor,
            project_key,
            ticket_key,
            payload,
        )
    except (ValidationError, AuthError, ValueError) as error:
        if isinstance(error, AuthError) and error.status_code in {401, 403, 404}:
            raise
        return _render_ticket_detail_page(
            request,
            session,
            actor,
            project_key,
            ticket_key,
            reply_comment_id=int(parent_comment_id) if parent_comment_id.isdecimal() else None,
            comment_form_values=comment_form_values,
            comment_error=_comment_form_error_message(
                error,
                "댓글 내용을 확인하세요.",
            ),
            status_code=error.status_code if isinstance(error, AuthError) else 422,
        )
    return RedirectResponse(
        f"/projects/{project_key}/tickets/{ticket_key}"
        f"?comment_created=1#comment-{created_comment.id}",
        status_code=303,
    )


@router.post("/projects/{project_key}/tickets/{ticket_key}/comments/{comment_id}")
def update_comment_submit(
    project_key: str,
    ticket_key: str,
    comment_id: int,
    request: Request,
    session: Database,
    actor: Actor,
    body_document: Annotated[str, Form()] = "",
    expected_version: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """티켓 댓글 form 수정을 처리한다."""
    verify_csrf(request, csrf_token, actor, get_settings())
    comment_form_values = {
        "body_document_json": body_document[:MAX_DOCUMENT_BYTES],
        "expected_version": expected_version[:20],
    }
    try:
        payload = CommentUpdate(
            body_document=_parse_comment_document(body_document),
            expected_version=expected_version,
        )
        comment_service.update_comment(
            session,
            actor,
            project_key,
            ticket_key,
            comment_id,
            payload,
        )
    except (ValidationError, AuthError, ValueError) as error:
        if isinstance(error, AuthError) and error.status_code in {401, 403, 404}:
            raise
        return _render_ticket_detail_page(
            request,
            session,
            actor,
            project_key,
            ticket_key,
            edit_comment_id=comment_id,
            comment_form_values=comment_form_values,
            comment_error=_comment_form_error_message(
                error,
                "댓글 내용과 현재 버전을 확인하세요.",
            ),
            comment_conflict=isinstance(error, AuthError)
            and error.code == "comment_version_conflict",
            status_code=error.status_code if isinstance(error, AuthError) else 422,
        )
    return RedirectResponse(
        f"/projects/{project_key}/tickets/{ticket_key}?comment_updated=1#comment-{comment_id}",
        status_code=303,
    )


@router.post("/projects/{project_key}/tickets/{ticket_key}/comments/{comment_id}/delete")
def delete_comment_submit(
    project_key: str,
    ticket_key: str,
    comment_id: int,
    request: Request,
    session: Database,
    actor: Actor,
    expected_version: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """티켓 댓글 form soft delete를 처리한다."""
    verify_csrf(request, csrf_token, actor, get_settings())
    try:
        payload = CommentDelete(expected_version=expected_version)
        comment_service.delete_comment(
            session,
            actor,
            project_key,
            ticket_key,
            comment_id,
            payload,
        )
    except (ValidationError, AuthError) as error:
        if isinstance(error, AuthError) and error.status_code in {401, 403, 404}:
            raise
        return _render_ticket_detail_page(
            request,
            session,
            actor,
            project_key,
            ticket_key,
            comment_error=error.message
            if isinstance(error, AuthError)
            else "댓글 삭제 요청과 현재 버전을 확인하세요.",
            status_code=error.status_code if isinstance(error, AuthError) else 422,
        )
    return RedirectResponse(
        f"/projects/{project_key}/tickets/{ticket_key}?comment_deleted=1#comments",
        status_code=303,
    )


@router.post("/projects/{project_key}/tickets/{ticket_key}/attachments")
def upload_ticket_attachment_page(
    project_key: str,
    ticket_key: str,
    request: Request,
    session: Database,
    actor: Actor,
    storage: Storage,
    file: Annotated[UploadFile, File()],
    expected_version: Annotated[int, Form(gt=0)],
    csrf_token: Annotated[str, Form()],
):
    """티켓 상세 화면의 일반 첨부파일 업로드 form을 처리한다."""
    verify_csrf(request, csrf_token, actor, get_settings())
    try:
        attachment_service.upload_ticket_attachment(
            session,
            actor,
            project_key,
            ticket_key,
            raw_filename=file.filename,
            declared_media_type=file.content_type,
            source=file.file,
            expected_version=expected_version,
            storage=storage,
        )
    except AuthError as error:
        return _render_ticket_detail_page(
            request,
            session,
            actor,
            project_key,
            ticket_key,
            attachment_error=error.message,
            status_code=error.status_code,
        )
    return RedirectResponse(
        f"/projects/{project_key}/tickets/{ticket_key}?attachment_uploaded=1#attachments",
        status_code=303,
    )


@router.get("/projects/{project_key}/tickets/{ticket_key}/attachments/{attachment_id}/download")
def download_ticket_attachment_page(
    project_key: str,
    ticket_key: str,
    attachment_id: int,
    session: Database,
    actor: Actor,
    storage: Storage,
):
    """티켓 상세 화면에서 권한이 확인된 일반 첨부파일을 다운로드한다."""
    download = attachment_service.open_ticket_attachment_download(
        session,
        actor,
        project_key,
        ticket_key,
        attachment_id,
        storage,
    )
    return build_attachment_download_response(download)


@router.get("/projects/{project_key}/tickets/{ticket_key}")
def ticket_detail_page(
    project_key: str,
    ticket_key: str,
    request: Request,
    session: Database,
    actor: Actor,
    created: bool = False,
    updated: bool = False,
    transitioned: bool = False,
    relation_created: bool = False,
    relation_deleted: bool = False,
    comment_created: bool = False,
    comment_updated: bool = False,
    comment_deleted: bool = False,
    attachment_uploaded: bool = False,
    edit_comment: int | None = None,
    reply_to: int | None = None,
):
    """티켓 상세 화면을 렌더링한다."""
    return _render_ticket_detail_page(
        request,
        session,
        actor,
        project_key,
        ticket_key,
        created=created,
        updated=updated,
        transitioned=transitioned,
        relation_created=relation_created,
        relation_deleted=relation_deleted,
        comment_created=comment_created,
        comment_updated=comment_updated,
        comment_deleted=comment_deleted,
        attachment_uploaded=attachment_uploaded,
        edit_comment_id=edit_comment,
        reply_comment_id=reply_to,
    )
