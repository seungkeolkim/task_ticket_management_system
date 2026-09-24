from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import Identity
from app.schemas.administration import OrganizationCreate, OrganizationView, UserCreate, UserPage
from app.services import administration as service
from app.web.security import get_client_ip_address, require_api_admin, verify_csrf

router = APIRouter(prefix="/api/admin", tags=["administration"])
Database = Annotated[Session, Depends(get_db_session)]
Administrator = Annotated[Identity, Depends(require_api_admin)]


@router.get("/users", response_model=UserPage)
def list_administrator_users(
    session: Database,
    actor: Administrator,
    search_query: Annotated[str, Query(alias="q")] = "",
    page: int = 1,
    page_size: int | None = None,
):
    """관리자 사용자 목록을 조회한다."""
    return service.list_users(session, actor, search_query, page, page_size)


@router.get("/organizations", response_model=list[OrganizationView])
def list_administrator_organizations(session: Database, actor: Administrator):
    """관리자 조직 목록을 조회한다."""
    return service.list_organizations(session, actor)


@router.post("/users", status_code=201)
def create_user(request: Request, payload: UserCreate, session: Database, actor: Administrator):
    """사용자 생성을 처리한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return {"id": service.create_user(session, actor, payload, get_client_ip_address(request))}


@router.post("/organizations", status_code=201)
def create_organization(
    request: Request, payload: OrganizationCreate, session: Database, actor: Administrator
):
    """조직 생성을 처리한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return {
        "id": service.create_organization(session, actor, payload, get_client_ip_address(request))
    }
