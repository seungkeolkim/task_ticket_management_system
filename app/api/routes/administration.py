from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import Identity
from app.schemas.administration import OrganizationCreate, OrganizationView, UserCreate, UserPage
from app.services import administration as service
from app.web.security import client_ip, require_api_admin, verify_csrf

router = APIRouter(prefix="/api/admin", tags=["administration"])
Database = Annotated[Session, Depends(get_db_session)]
Administrator = Annotated[Identity, Depends(require_api_admin)]


@router.get("/users", response_model=UserPage)
def users(
    session: Database,
    actor: Administrator,
    q: str = "",
    page: int = 1,
    page_size: int | None = None,
):
    return service.user_list(session, actor, q, page, page_size)


@router.get("/organizations", response_model=list[OrganizationView])
def organizations(session: Database, actor: Administrator):
    return service.organization_list(session, actor)


@router.post("/users", status_code=201)
def create_user(request: Request, payload: UserCreate, session: Database, actor: Administrator):
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return {"id": service.create_user(session, actor, payload, client_ip(request))}


@router.post("/organizations", status_code=201)
def create_organization(
    request: Request, payload: OrganizationCreate, session: Database, actor: Administrator
):
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return {"id": service.create_organization(session, actor, payload, client_ip(request))}
