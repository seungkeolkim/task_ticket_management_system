from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import AuthError, Identity
from app.schemas.tickets import TicketCreate
from app.services import tickets as service
from app.web.rendering import render
from app.web.security import require_web_user, verify_csrf

router = APIRouter(include_in_schema=False)
Database = Annotated[Session, Depends(get_db_session)]
Actor = Annotated[Identity, Depends(require_web_user)]


def _create_page(request, session, actor, project_key, **context):
    project, options = service.create_options(session, actor, project_key)
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


@router.get("/projects/{project_key}/tickets")
def ticket_list(
    project_key: str,
    request: Request,
    session: Database,
    actor: Actor,
    q: str = "",
    page: int = 1,
    page_size: int | None = None,
    selected: str | None = None,
    created: bool = False,
):
    project, result = service.ticket_list(
        session, actor, project_key, q=q, page=page, page_size=page_size
    )
    selected_ticket = None
    if selected:
        _, selected_ticket = service.ticket_detail(session, actor, project_key, selected)
    query = {"q": q, "page_size": result.page_size}
    return render(
        request,
        "ticket_list.html",
        live_page=True,
        page_title=f"티켓 · {project.key}",
        active="tickets",
        project=project,
        result=result,
        q=q,
        selected_ticket=selected_ticket,
        created=created,
        previous_url=f"/projects/{project.key}/tickets?"
        + urlencode(query | {"page": page - 1}),
        next_url=f"/projects/{project.key}/tickets?" + urlencode(query | {"page": page + 1}),
    )


@router.get("/projects/{project_key}/tickets/new")
def new_ticket(project_key: str, request: Request, session: Database, actor: Actor):
    return _create_page(request, session, actor, project_key)


@router.post("/projects/{project_key}/tickets")
def create_ticket(
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
        return _create_page(
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


@router.get("/projects/{project_key}/tickets/{ticket_key}")
def ticket_detail(
    project_key: str,
    ticket_key: str,
    request: Request,
    session: Database,
    actor: Actor,
    created: bool = False,
):
    project, ticket = service.ticket_detail(session, actor, project_key, ticket_key)
    return render(
        request,
        "ticket_detail.html",
        live_page=True,
        page_title=f"{ticket.key} · {ticket.title}",
        active="tickets",
        project=project,
        ticket=ticket,
        created=created,
    )
