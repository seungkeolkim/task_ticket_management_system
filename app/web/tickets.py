from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import AuthError, Identity
from app.schemas.tickets import TicketCreate, TicketTransition, TicketUpdate
from app.services import tickets as service
from app.web.rendering import render
from app.web.security import require_web_user, verify_csrf

router = APIRouter(include_in_schema=False)
Database = Annotated[Session, Depends(get_db_session)]
Actor = Annotated[Identity, Depends(require_web_user)]


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


@router.get("/projects/{project_key}/board")
def project_ticket_board_page(
    project_key: str, request: Request, session: Database, actor: Actor
):
    project, board = service.build_ticket_board(session, actor, project_key)
    return render(
        request,
        "board.html",
        live_page=True,
        page_title=f"칸반 · {project.key}",
        active="board",
        project=project,
        board=board,
    )


def _render_ticket_create_page(request, session, actor, project_key, **context):
    project, options = service.get_ticket_creation_options(session, actor, project_key)
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
    project, ticket, options = service.get_ticket_edit_options(
        session, actor, project_key, ticket_key
    )
    values = context.pop(
        "values",
        {
            "title": ticket.title,
            "description": ticket.description,
            "priority": ticket.priority.value,
            "parent_key": ticket.parent.key if ticket.parent else "",
            "assignee_id": str(ticket.assignee.id) if ticket.assignee else "",
            "due_date": ticket.due_date.isoformat() if ticket.due_date else "",
            "expected_version": str(ticket.version),
        },
    )
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
        **context,
    )


def _render_ticket_detail_page(request, session, actor, project_key, ticket_key, **context):
    project, ticket = service.get_ticket_detail(session, actor, project_key, ticket_key)
    transitions = [
        (status, service.STATUS_LABELS[status][0])
        for status in service.get_allowed_transitions(ticket.status)
    ]
    return render(
        request,
        "ticket_detail.html",
        live_page=True,
        page_title=f"{ticket.key} · {ticket.title}",
        active="tickets",
        project=project,
        ticket=ticket,
        can_edit=service.can_edit_ticket(project, ticket, actor),
        transitions=transitions,
        **context,
    )


@router.get("/projects/{project_key}/tickets")
def project_ticket_list_page(
    project_key: str,
    request: Request,
    session: Database,
    actor: Actor,
    search_query: Annotated[str, Query(alias="q")] = "",
    page: int = 1,
    page_size: int | None = None,
    selected: str | None = None,
    created: bool = False,
):
    project, result = service.list_project_tickets(
        session,
        actor,
        project_key,
        search_query=search_query,
        page=page,
        page_size=page_size,
    )
    selected_ticket = None
    if selected:
        _, selected_ticket = service.get_ticket_detail(
            session, actor, project_key, selected
        )
    query = {"q": search_query, "page_size": result.page_size}
    return render(
        request,
        "ticket_list.html",
        live_page=True,
        page_title=f"티켓 · {project.key}",
        active="tickets",
        project=project,
        result=result,
        q=search_query,
        selected_ticket=selected_ticket,
        created=created,
        previous_url=f"/projects/{project.key}/tickets?"
        + urlencode(query | {"page": page - 1}),
        next_url=f"/projects/{project.key}/tickets?" + urlencode(query | {"page": page + 1}),
    )


@router.get("/projects/{project_key}/tickets/new")
def new_ticket_page(project_key: str, request: Request, session: Database, actor: Actor):
    return _render_ticket_create_page(request, session, actor, project_key)


@router.get("/projects/{project_key}/tickets/{ticket_key}/edit")
def edit_ticket_page(
    project_key: str,
    ticket_key: str,
    request: Request,
    session: Database,
    actor: Actor,
):
    return _render_ticket_edit_page(request, session, actor, project_key, ticket_key)


@router.post("/projects/{project_key}/tickets")
def create_ticket_submit(
    project_key: str,
    request: Request,
    session: Database,
    actor: Actor,
    type: Annotated[str, Form()] = "TASK",
    title: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    priority: Annotated[str, Form()] = "MAJOR",
    parent_key: Annotated[str, Form()] = "",
    assignee_id: Annotated[str, Form()] = "",
    due_date: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    verify_csrf(request, csrf_token, actor, get_settings())
    values = {
        "type": type[:16],
        "title": title[:200],
        "description": description[:100_000],
        "priority": priority[:16],
        "parent_key": parent_key[:64],
        "assignee_id": assignee_id[:20],
        "due_date": due_date[:10],
    }
    try:
        payload = TicketCreate(
            type=type,
            title=title,
            description=description,
            priority=priority,
            parent_key=parent_key,
            assignee_id=assignee_id or None,
            due_date=due_date or None,
        )
        ticket = service.create_ticket(session, actor, project_key, payload)
    except (ValidationError, AuthError) as error:
        if isinstance(error, AuthError) and error.status_code in {401, 403, 404}:
            raise
        return _render_ticket_create_page(
            request,
            session,
            actor,
            project_key,
            values=values,
            error=error.message
            if isinstance(error, AuthError)
            else "티켓 유형, 제목, 상위 티켓과 담당자를 확인하세요.",
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
    description: Annotated[str, Form()] = "",
    priority: Annotated[str, Form()] = "MAJOR",
    parent_key: Annotated[str, Form()] = "",
    assignee_id: Annotated[str, Form()] = "",
    due_date: Annotated[str, Form()] = "",
    expected_version: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    verify_csrf(request, csrf_token, actor, get_settings())
    values = {
        "title": title[:200],
        "description": description[:100_000],
        "priority": priority[:16],
        "parent_key": parent_key[:64],
        "assignee_id": assignee_id[:20],
        "due_date": due_date[:10],
        "expected_version": expected_version[:20],
    }
    try:
        payload = TicketUpdate(
            title=title,
            description=description,
            priority=priority,
            parent_key=parent_key,
            assignee_id=assignee_id or None,
            due_date=due_date or None,
            expected_version=expected_version,
        )
        ticket = service.update_ticket(session, actor, project_key, ticket_key, payload)
    except (ValidationError, AuthError) as error:
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
            error=error.message
            if isinstance(error, AuthError)
            else "제목, 상위 티켓과 담당자를 확인하세요.",
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
    verify_csrf(request, csrf_token, actor, get_settings())
    try:
        payload = TicketTransition(
            target_status=target_status,
            expected_version=expected_version,
            confirm_incomplete_children=confirm_incomplete_children,
        )
        ticket = service.transition_ticket(
            session, actor, project_key, ticket_key, payload
        )
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
            error=error.message
            if isinstance(error, AuthError)
            else "상태 변경 요청을 확인하세요.",
            confirmation_status=target_status if confirmation else None,
            status_code=error.status_code if isinstance(error, AuthError) else 422,
        )
    return RedirectResponse(
        f"/projects/{project_key}/tickets/{ticket.key}?transitioned=1", status_code=303
    )


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
):
    return _render_ticket_detail_page(
        request,
        session,
        actor,
        project_key,
        ticket_key,
        created=created,
        updated=updated,
        transitioned=transitioned,
    )
