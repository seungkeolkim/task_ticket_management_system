from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
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


def list_page(
    request, session, actor, *, admin=False, q="", page=1, page_size=None, candidate_q="", **context
):
    result = service.project_list(
        session, actor, all_projects=admin, q=q, page=page, page_size=page_size
    )
    path = "/admin/projects" if admin else "/projects"
    query = {"q": q, "page_size": result.page_size}
    return render(
        request,
        "projects.html",
        live_page=True,
        admin_page=admin,
        page_title="전체 프로젝트 관리" if admin else "내 프로젝트",
        active="admin-projects" if admin else "projects",
        result=result,
        q=q,
        candidates=service.candidate_list(session, actor, q=candidate_q) if admin else [],
        candidate_q=candidate_q,
        previous_url=path + "?" + urlencode(query | {"page": page - 1}),
        next_url=path + "?" + urlencode(query | {"page": page + 1}),
        **context,
    )


@router.get("/projects")
def mine(
    request: Request,
    session: Database,
    actor: Actor,
    q: str = "",
    page: int = 1,
    page_size: int | None = None,
):
    return list_page(request, session, actor, q=q, page=page, page_size=page_size)


@router.get("/admin/projects")
def all_projects(
    request: Request,
    session: Database,
    actor: Administrator,
    q: str = "",
    page: int = 1,
    page_size: int | None = None,
    candidate_q: str = "",
):
    return list_page(
        request,
        session,
        actor,
        admin=True,
        q=q,
        page=page,
        page_size=page_size,
        candidate_q=candidate_q,
    )


@router.post("/admin/projects")
def create(
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
        return list_page(
            request,
            session,
            actor,
            admin=True,
            values=values,
            candidate_q=candidate_q[:100],
            error=error.message
            if isinstance(error, AuthError)
            else "키(영문자로 시작하는 영문·숫자 2~32자), 이름과 관리자를 확인하세요.",
            status_code=error.status_code if isinstance(error, AuthError) else 422,
        )
    return RedirectResponse(f"/projects/{payload.key}?created=1", status_code=303)


def detail_page(request, session, actor, key, *, member_page=False, candidate_q="", **context):
    detail = service.project_detail(session, actor, key)
    project = detail.project
    candidates = (
        service.candidate_list(session, actor, key=key, q=candidate_q)
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
        candidate_q=candidate_q,
        **context,
    )


@router.get("/projects/{project_key}")
@router.get("/projects/{project_key}/settings")
def overview(
    project_key: str, request: Request, session: Database, actor: Actor, created: bool = False
):
    return detail_page(request, session, actor, project_key, created=created)


@router.get("/projects/{project_key}/members")
def members(
    project_key: str,
    request: Request,
    session: Database,
    actor: Actor,
    candidate_q: str = "",
    added: bool = False,
):
    return detail_page(
        request, session, actor, project_key, member_page=True, candidate_q=candidate_q, added=added
    )


@router.post("/projects/{project_key}/members")
def add_member(
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
        service.add_member(session, actor, project_key, MemberCreate(user_id=user_id, role=role))
    except (ValidationError, AuthError) as error:
        if isinstance(error, AuthError) and error.status_code in {401, 403, 404}:
            raise
        return detail_page(
            request,
            session,
            actor,
            project_key,
            member_page=True,
            candidate_q=candidate_q[:100],
            values={"user_id": user_id[:20], "role": role[:32]},
            error=error.message
            if isinstance(error, AuthError)
            else "사용자와 프로젝트 역할을 확인하세요.",
            status_code=error.status_code if isinstance(error, AuthError) else 422,
        )
    return RedirectResponse(f"/projects/{project_key}/members?added=1", status_code=303)


@router.get("/projects/{project_key}/tickets")
@router.get("/projects/{project_key}/tickets/new")
@router.get("/projects/{project_key}/tickets/{ticket_key}")
@router.get("/projects/{project_key}/tickets/{ticket_key}/edit")
@router.get("/projects/{project_key}/board")
@router.get("/projects/{project_key}/trash")
def pending(project_key: str, request: Request, session: Database, actor: Actor):
    return detail_page(request, session, actor, project_key, pending=True)
