from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import Identity
from app.schemas.tickets import TicketCreate, TicketCreateOptions, TicketPage, TicketView
from app.services import tickets as service
from app.web.security import require_api_user, verify_csrf

router = APIRouter(prefix="/api/projects/{project_key}/tickets", tags=["tickets"])
Database = Annotated[Session, Depends(get_db_session)]
Actor = Annotated[Identity, Depends(require_api_user)]


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


@router.get("/{ticket_key}", response_model=TicketView)
def ticket_detail(project_key: str, ticket_key: str, session: Database, actor: Actor):
    return service.ticket_detail(session, actor, project_key, ticket_key)[1]
