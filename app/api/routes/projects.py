from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import Identity
from app.schemas.projects import (
    CandidateView,
    MemberCreate,
    MemberRoleUpdate,
    MemberView,
    ProjectCreate,
    ProjectDetail,
    ProjectPage,
    ProjectUpdate,
    ProjectView,
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
    """my 프로젝트 목록을 조회한다."""
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
    """all 프로젝트 목록을 조회한다."""
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
    """프로젝트 관리자 후보 목록을 조회한다."""
    return service.list_project_candidates(session, actor, search_query=search_query)


@router.post("/admin/projects", status_code=201)
def create_project(
    request: Request, payload: ProjectCreate, session: Database, actor: Administrator
):
    """프로젝트 생성을 처리한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return {"id": service.create_project(session, actor, payload), "key": payload.key}


@router.get("/projects/{project_key}", response_model=ProjectDetail)
def get_project_detail(project_key: str, session: Database, actor: Actor):
    """프로젝트 상세 정보를 조회한다."""
    return service.get_project_detail(session, actor, project_key)


@router.patch("/projects/{project_key}", response_model=ProjectView)
def update_project(
    project_key: str,
    request: Request,
    payload: ProjectUpdate,
    session: Database,
    actor: Actor,
):
    """프로젝트 기본 정보와 활성 상태를 변경한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.update_project(session, actor, project_key, payload)


@router.get("/projects/{project_key}/members", response_model=list[MemberView])
def list_project_members(project_key: str, session: Database, actor: Actor):
    """프로젝트 구성원 목록을 조회한다."""
    return service.get_project_detail(session, actor, project_key).members


@router.get("/projects/{project_key}/candidates", response_model=list[CandidateView])
def list_project_candidates(
    project_key: str,
    session: Database,
    actor: Actor,
    search_query: Annotated[str, Query(alias="q")] = "",
):
    """프로젝트 후보 목록을 조회한다."""
    return service.list_project_candidates(
        session, actor, project_key=project_key, search_query=search_query
    )


@router.post("/projects/{project_key}/members", status_code=201)
def add_project_member(
    project_key: str, request: Request, payload: MemberCreate, session: Database, actor: Actor
):
    """프로젝트 구성원 추가를 처리한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return {"id": service.add_project_member(session, actor, project_key, payload)}


@router.patch(
    "/projects/{project_key}/members/{member_id}",
    response_model=MemberView,
)
def update_project_member_role(
    project_key: str,
    member_id: int,
    request: Request,
    payload: MemberRoleUpdate,
    session: Database,
    actor: Actor,
):
    """프로젝트 참여자 역할을 변경한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.update_project_member_role(session, actor, project_key, member_id, payload)


@router.delete(
    "/projects/{project_key}/members/{member_id}",
    status_code=204,
    response_class=Response,
)
def remove_project_member(
    project_key: str,
    member_id: int,
    request: Request,
    session: Database,
    actor: Actor,
) -> Response:
    """프로젝트 참여자를 제거한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    service.remove_project_member(session, actor, project_key, member_id)
    return Response(status_code=204)
