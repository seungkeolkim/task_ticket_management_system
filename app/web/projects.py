from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import AuthError, Identity
from app.schemas.projects import MemberCreate, ProjectCreate
from app.services import projects as service
from app.web.rendering import render
from app.web.security import require_web_admin, require_web_user, verify_csrf

router = APIRouter(include_in_schema=False)
Database = Annotated[Session, Depends(get_db_session)]
Actor = Annotated[Identity, Depends(require_web_user)]
Administrator = Annotated[Identity, Depends(require_web_admin)]


def render_project_list_page(
    request,
    session,
    actor,
    *,
    is_administrator_page=False,
    search_query="",
    page=1,
    page_size=None,
    candidate_search_query="",
    **context,
):
    result = service.list_projects(
        session,
        actor,
        include_all_projects=is_administrator_page,
        search_query=search_query,
        page=page,
        page_size=page_size,
    )
    path = "/admin/projects" if is_administrator_page else "/projects"
    query = {"q": search_query, "page_size": result.page_size}
    return render(
        request,
        "projects.html",
        live_page=True,
        admin_page=is_administrator_page,
        page_title="전체 프로젝트 관리" if is_administrator_page else "내 프로젝트",
        active="admin-projects" if is_administrator_page else "projects",
        result=result,
        q=search_query,
        candidates=(
            service.list_project_candidates(
                session, actor, search_query=candidate_search_query
            )
            if is_administrator_page
            else []
        ),
        candidate_q=candidate_search_query,
        previous_url=path + "?" + urlencode(query | {"page": page - 1}),
        next_url=path + "?" + urlencode(query | {"page": page + 1}),
        **context,
    )


@router.get("/projects")
def my_projects_page(
    request: Request,
    session: Database,
    actor: Actor,
    search_query: Annotated[str, Query(alias="q")] = "",
    page: int = 1,
    page_size: int | None = None,
):
    return render_project_list_page(
        request,
        session,
        actor,
        search_query=search_query,
        page=page,
        page_size=page_size,
    )


@router.get("/admin/projects")
def all_projects_page(
    request: Request,
    session: Database,
    actor: Administrator,
    search_query: Annotated[str, Query(alias="q")] = "",
    page: int = 1,
    page_size: int | None = None,
    candidate_search_query: Annotated[str, Query(alias="candidate_q")] = "",
):
    return render_project_list_page(
        request,
        session,
        actor,
        is_administrator_page=True,
        search_query=search_query,
        page=page,
        page_size=page_size,
        candidate_search_query=candidate_search_query,
    )


@router.post("/admin/projects")
def create_project(
    request: Request,
    session: Database,
    actor: Administrator,
    key: Annotated[str, Form()] = "",
    name: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    administrator_id: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
    candidate_q: Annotated[str, Form()] = "",
):
    verify_csrf(request, csrf_token, actor, get_settings())
    values = dict(
        key=key[:32],
        name=name[:200],
        description=description[:4000],
        administrator_id=administrator_id[:20],
    )
    try:
        payload = ProjectCreate(
            key=key, name=name, description=description, administrator_id=administrator_id
        )
        service.create_project(session, actor, payload)
    except (ValidationError, AuthError) as error:
        return render_project_list_page(
            request,
            session,
            actor,
            is_administrator_page=True,
            values=values,
            candidate_search_query=candidate_q[:100],
            error=error.message
            if isinstance(error, AuthError)
            else "키(영문자로 시작하는 영문·숫자 2~32자), 이름과 관리자를 확인하세요.",
            status_code=error.status_code if isinstance(error, AuthError) else 422,
        )
    return RedirectResponse(f"/projects/{payload.key}?created=1", status_code=303)


def render_project_detail_page(
    request,
    session,
    actor,
    project_key,
    *,
    member_page=False,
    candidate_search_query="",
    **context,
):
    detail = service.get_project_detail(session, actor, project_key)
    project = detail.project
    candidates = (
        service.list_project_candidates(
            session,
            actor,
            project_key=project_key,
            search_query=candidate_search_query,
        )
        if (member_page and project.can_manage and project.is_active)
        else []
    )
    return render(
        request,
        "project_members.html" if member_page else "project_overview.html",
        live_page=True,
        page_title=f"{project.name} · 프로젝트",
        active="project-members" if member_page else "project-settings",
        project=project,
        members=detail.members,
        candidates=candidates,
        candidate_q=candidate_search_query,
        **context,
    )


@router.get("/projects/{project_key}")
@router.get("/projects/{project_key}/settings")
def project_overview_page(
    project_key: str, request: Request, session: Database, actor: Actor, created: bool = False
):
    return render_project_detail_page(request, session, actor, project_key, created=created)


@router.get("/projects/{project_key}/members")
def project_members_page(
    project_key: str,
    request: Request,
    session: Database,
    actor: Actor,
    candidate_search_query: Annotated[str, Query(alias="candidate_q")] = "",
    added: bool = False,
):
    return render_project_detail_page(
        request,
        session,
        actor,
        project_key,
        member_page=True,
        candidate_search_query=candidate_search_query,
        added=added,
    )


@router.post("/projects/{project_key}/members")
def add_project_member(
    project_key: str,
    request: Request,
    session: Database,
    actor: Actor,
    user_id: Annotated[str, Form()] = "",
    role: Annotated[str, Form()] = "PROJECT_USER",
    csrf_token: Annotated[str, Form()] = "",
    candidate_q: Annotated[str, Form()] = "",
):
    verify_csrf(request, csrf_token, actor, get_settings())
    try:
        service.add_project_member(
            session, actor, project_key, MemberCreate(user_id=user_id, role=role)
        )
    except (ValidationError, AuthError) as error:
        if isinstance(error, AuthError) and error.status_code in {401, 403, 404}:
            raise
        return render_project_detail_page(
            request,
            session,
            actor,
            project_key,
            member_page=True,
            candidate_search_query=candidate_q[:100],
            values={"user_id": user_id[:20], "role": role[:32]},
            error=error.message
            if isinstance(error, AuthError)
            else "사용자와 프로젝트 역할을 확인하세요.",
            status_code=error.status_code if isinstance(error, AuthError) else 422,
        )
    return RedirectResponse(f"/projects/{project_key}/members?added=1", status_code=303)


@router.get("/projects/{project_key}/trash")
def project_trash_page(project_key: str, request: Request, session: Database, actor: Actor):
    return render_project_detail_page(request, session, actor, project_key, pending=True)
