from typing import Annotated

from fastapi import APIRouter, Depends, Request
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
def mine(session: Database, actor: Actor, q: str = "", page: int = 1, page_size: int | None = None):
    return service.project_list(session, actor, q=q, page=page, page_size=page_size)


@router.get("/admin/projects", response_model=ProjectPage)
def all_projects(
    session: Database,
    actor: Administrator,
    q: str = "",
    page: int = 1,
    page_size: int | None = None,
):
    return service.project_list(
        session, actor, all_projects=True, q=q, page=page, page_size=page_size
    )


@router.get("/admin/project-candidates", response_model=list[CandidateView])
def administrators(session: Database, actor: Administrator, q: str = ""):
    return service.candidate_list(session, actor, q=q)


@router.post("/admin/projects", status_code=201)
def create(request: Request, payload: ProjectCreate, session: Database, actor: Administrator):
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return {"id": service.create_project(session, actor, payload), "key": payload.key}


@router.get("/projects/{key}", response_model=ProjectDetail)
def detail(key: str, session: Database, actor: Actor):
    return service.project_detail(session, actor, key)


@router.get("/projects/{key}/members", response_model=list[MemberView])
def members(key: str, session: Database, actor: Actor):
    return service.project_detail(session, actor, key).members


@router.get("/projects/{key}/candidates", response_model=list[CandidateView])
def candidates(key: str, session: Database, actor: Actor, q: str = ""):
    return service.candidate_list(session, actor, key=key, q=q)


@router.post("/projects/{key}/members", status_code=201)
def add(key: str, request: Request, payload: MemberCreate, session: Database, actor: Actor):
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return {"id": service.add_member(session, actor, key, payload)}
