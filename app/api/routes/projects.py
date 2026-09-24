from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import Identity
from app.schemas.projects import (
    CandidateView,
    MemberCreate,
    MemberView,
    ProjectCreate,
    ProjectDetail,
    ProjectPage,
)
from app.services import projects as service
from app.web.security import require_api_admin, require_api_user, verify_csrf

router = APIRouter(prefix="/api", tags=["projects"])
Database = Annotated[Session, Depends(get_db_session)]
Actor = Annotated[Identity, Depends(require_api_user)]
Administrator = Annotated[Identity, Depends(require_api_admin)]


@router.get("/projects", response_model=ProjectPage)
def list_my_projects(
    session: Database,
    actor: Actor,
    search_query: Annotated[str, Query(alias="q")] = "",
    page: int = 1,
    page_size: int | None = None,
):
    return service.list_projects(
        session, actor, search_query=search_query, page=page, page_size=page_size
    )


@router.get("/admin/projects", response_model=ProjectPage)
def list_all_projects(
    session: Database,
    actor: Administrator,
    search_query: Annotated[str, Query(alias="q")] = "",
    page: int = 1,
    page_size: int | None = None,
):
    return service.list_projects(
        session,
        actor,
        include_all_projects=True,
        search_query=search_query,
        page=page,
        page_size=page_size,
    )


@router.get("/admin/project-candidates", response_model=list[CandidateView])
def list_project_administrator_candidates(
    session: Database, actor: Administrator, search_query: Annotated[str, Query(alias="q")] = ""
):
    return service.list_project_candidates(session, actor, search_query=search_query)


@router.post("/admin/projects", status_code=201)
def create_project(
    request: Request, payload: ProjectCreate, session: Database, actor: Administrator
):
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return {"id": service.create_project(session, actor, payload), "key": payload.key}


@router.get("/projects/{project_key}", response_model=ProjectDetail)
def get_project_detail(project_key: str, session: Database, actor: Actor):
    return service.get_project_detail(session, actor, project_key)


@router.get("/projects/{project_key}/members", response_model=list[MemberView])
def list_project_members(project_key: str, session: Database, actor: Actor):
    return service.get_project_detail(session, actor, project_key).members


@router.get("/projects/{project_key}/candidates", response_model=list[CandidateView])
def list_project_candidates(
    project_key: str,
    session: Database,
    actor: Actor,
    search_query: Annotated[str, Query(alias="q")] = "",
):
    return service.list_project_candidates(
        session, actor, project_key=project_key, search_query=search_query
    )


@router.post("/projects/{project_key}/members", status_code=201)
def add_project_member(
    project_key: str, request: Request, payload: MemberCreate, session: Database, actor: Actor
):
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return {"id": service.add_project_member(session, actor, project_key, payload)}
