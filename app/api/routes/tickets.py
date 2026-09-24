from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import Identity
from app.schemas.tickets import (
    BoardView,
    TicketCreate,
    TicketCreateOptions,
    TicketDetailView,
    TicketPage,
    TicketRelationCreate,
    TicketRelationDelete,
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
def list_global_tickets_api(
    session: Database,
    actor: Actor,
    scope: str = "mine",
    status: str = "open",
    due: str = "all",
    search_query: Annotated[str, Query(alias="q")] = "",
    page: int = 1,
    page_size: int | None = None,
):
    """전체 티켓 API 목록을 조회한다."""
    return service.list_global_tickets(
        session,
        actor,
        scope=scope,
        status=status,
        due=due,
        search_query=search_query,
        page=page,
        page_size=page_size,
    )


@router.get("", response_model=TicketPage)
def list_project_tickets_api(
    project_key: str,
    session: Database,
    actor: Actor,
    search_query: Annotated[str, Query(alias="q")] = "",
    page: int = 1,
    page_size: int | None = None,
):
    """프로젝트 티켓 API 목록을 조회한다."""
    return service.list_project_tickets(
        session, actor, project_key, search_query=search_query, page=page, page_size=page_size
    )[1]


@router.get("/creation-options", response_model=TicketCreateOptions)
def get_ticket_creation_options_api(project_key: str, session: Database, actor: Actor):
    """티켓 creation options API 정보를 조회한다."""
    return service.get_ticket_creation_options(session, actor, project_key)[1]


@router.post("", response_model=TicketView, status_code=201)
def create_ticket_api(
    project_key: str, request: Request, payload: TicketCreate, session: Database, actor: Actor
):
    """티켓 API 생성을 처리한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.create_ticket(session, actor, project_key, payload)


@router.get("/board", response_model=BoardView)
def get_ticket_board_api(project_key: str, session: Database, actor: Actor):
    """티켓 보드 API 정보를 조회한다."""
    return service.build_ticket_board(session, actor, project_key)[1]


@router.patch("/{ticket_key}", response_model=TicketView)
def update_ticket_api(
    project_key: str,
    ticket_key: str,
    request: Request,
    payload: TicketUpdate,
    session: Database,
    actor: Actor,
):
    """티켓 API 수정을 처리한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.update_ticket(session, actor, project_key, ticket_key, payload)


@router.post("/{ticket_key}/transitions", response_model=TicketView)
def transition_ticket_api(
    project_key: str,
    ticket_key: str,
    request: Request,
    payload: TicketTransition,
    session: Database,
    actor: Actor,
):
    """티켓 API 상태 전이를 처리한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.transition_ticket(session, actor, project_key, ticket_key, payload)


@router.post("/{ticket_key}/relations", response_model=TicketDetailView, status_code=201)
def create_ticket_relation_api(
    project_key: str,
    ticket_key: str,
    request: Request,
    payload: TicketRelationCreate,
    session: Database,
    actor: Actor,
):
    """티켓 관계 API 생성을 처리한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.create_ticket_relation(session, actor, project_key, ticket_key, payload)


@router.delete("/{ticket_key}/relations/{relation_id}", response_model=TicketDetailView)
def delete_ticket_relation_api(
    project_key: str,
    ticket_key: str,
    relation_id: int,
    request: Request,
    payload: TicketRelationDelete,
    session: Database,
    actor: Actor,
):
    """티켓 관계 API 삭제를 처리한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.delete_ticket_relation(
        session, actor, project_key, ticket_key, relation_id, payload
    )


@router.get("/{ticket_key}", response_model=TicketDetailView)
def get_ticket_detail_api(project_key: str, ticket_key: str, session: Database, actor: Actor):
    """티켓 상세 API 정보를 조회한다."""
    return service.get_ticket_detail(session, actor, project_key, ticket_key)[1]
