from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import Identity
from app.schemas.tickets import (
    BoardView,
    TicketCreate,
    TicketCreateOptions,
    TicketPage,
    TicketTransition,
    TicketUpdate,
    TicketView,
)
from app.services import tickets as service
from app.web.security import require_api_user, verify_csrf

router = APIRouter(prefix="/api/projects/{project_key}/tickets", tags=["tickets"])
global_router = APIRouter(prefix="/api/tickets", tags=["tickets"])
Database = Annotated[Session, Depends(get_db_session)]
Actor = Annotated[Identity, Depends(require_api_user)]


@global_router.get("", response_model=TicketPage)
def global_ticket_list(
    session: Database,
    actor: Actor,
    scope: str = "mine",
    status: str = "open",
    due: str = "all",
    q: str = "",
    page: int = 1,
    page_size: int | None = None,
):
    return service.global_ticket_list(
        session,
        actor,
        scope=scope,
        status=status,
        due=due,
        q=q,
        page=page,
        page_size=page_size,
    )


@router.get("", response_model=TicketPage)
def ticket_list(
    project_key: str,
    session: Database,
    actor: Actor,
    q: str = "",
    page: int = 1,
    page_size: int | None = None,
):
    return service.ticket_list(
        session, actor, project_key, q=q, page=page, page_size=page_size
    )[1]


@router.get("/creation-options", response_model=TicketCreateOptions)
def creation_options(project_key: str, session: Database, actor: Actor):
    return service.create_options(session, actor, project_key)[1]


@router.post("", response_model=TicketView, status_code=201)
def create_ticket(
    project_key: str,
    request: Request,
    payload: TicketCreate,
    session: Database,
    actor: Actor,
):
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.create_ticket(session, actor, project_key, payload)


@router.get("/board", response_model=BoardView)
def ticket_board(project_key: str, session: Database, actor: Actor):
    return service.board(session, actor, project_key)[1]


@router.patch("/{ticket_key}", response_model=TicketView)
def update_ticket(
    project_key: str,
    ticket_key: str,
    request: Request,
    payload: TicketUpdate,
    session: Database,
    actor: Actor,
):
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.update_ticket(session, actor, project_key, ticket_key, payload)


@router.post("/{ticket_key}/transitions", response_model=TicketView)
def transition_ticket(
    project_key: str,
    ticket_key: str,
    request: Request,
    payload: TicketTransition,
    session: Database,
    actor: Actor,
):
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.transition_ticket(session, actor, project_key, ticket_key, payload)


@router.get("/{ticket_key}", response_model=TicketView)
def ticket_detail(project_key: str, ticket_key: str, session: Database, actor: Actor):
    return service.ticket_detail(session, actor, project_key, ticket_key)[1]
