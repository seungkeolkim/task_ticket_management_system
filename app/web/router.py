from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.web.mock_data import (
    MEMBERS,
    MENTIONS,
    ORGANIZATION_TREE,
    PROJECTS,
    TICKETS,
    TRASH_TICKETS,
    USERS,
)
from app.web.rendering import STATIC_DIRECTORY, render  # noqa: F401
from app.web.security import require_web_admin, require_web_user

router = APIRouter(include_in_schema=False, dependencies=[Depends(require_web_user)])


def _project(project_key: str) -> dict[str, Any]:
    project = next((item for item in PROJECTS if item["key"] == project_key), None)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _ticket(project_key: str, ticket_key: str) -> dict[str, Any]:
    ticket = next(
        (
            item
            for item in TICKETS
            if item["project_key"] == project_key and item["key"] == ticket_key
        ),
        None,
    )
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


def _render(
    request: Request,
    template_name: str,
    *,
    page_title: str,
    active: str,
    project: dict[str, Any] | None = None,
    **context: Any,
) -> HTMLResponse:
    return render(
        request,
        template_name,
        **{
            "page_title": page_title,
            "active": active,
            "projects": PROJECTS,
            "project": project,
            **context,
        },
    )


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    return _render(
        request,
        "dashboard.html",
        page_title="내 작업",
        active="dashboard",
        tickets=TICKETS,
        mentions=MENTIONS,
    )


@router.get("/dashboard", include_in_schema=False)
def dashboard_alias() -> RedirectResponse:
    return RedirectResponse(url="/", status_code=307)


@router.get("/projects", response_class=HTMLResponse)
def project_list(request: Request) -> HTMLResponse:
    return _render(request, "projects.html", page_title="내 프로젝트", active="projects")


@router.get("/projects/{project_key}", include_in_schema=False)
def project_home(project_key: str) -> RedirectResponse:
    _project(project_key)
    return RedirectResponse(url=f"/projects/{project_key}/tickets", status_code=307)


@router.get("/projects/{project_key}/tickets", response_class=HTMLResponse)
def ticket_list(
    request: Request,
    project_key: str,
    selected: str | None = Query(default=None),
) -> HTMLResponse:
    project = _project(project_key)
    project_tickets = [item for item in TICKETS if item["project_key"] == project_key]
    selected_key = selected or (project_tickets[0]["key"] if project_tickets else None)
    selected_ticket = _ticket(project_key, selected_key) if selected_key is not None else None
    return _render(
        request,
        "ticket_list.html",
        page_title=f"{project['name']} · 티켓",
        active="tickets",
        project=project,
        tickets=project_tickets,
        selected_ticket=selected_ticket,
    )


@router.get("/projects/{project_key}/tickets/new", response_class=HTMLResponse)
def ticket_create(request: Request, project_key: str) -> HTMLResponse:
    project = _project(project_key)
    return _render(
        request,
        "ticket_form.html",
        page_title="새 티켓",
        active="tickets",
        project=project,
        mode="create",
        ticket=None,
        members=MEMBERS,
    )


@router.get(
    "/projects/{project_key}/tickets/{ticket_key}/edit",
    response_class=HTMLResponse,
)
def ticket_edit(request: Request, project_key: str, ticket_key: str) -> HTMLResponse:
    project = _project(project_key)
    ticket = _ticket(project_key, ticket_key)
    return _render(
        request,
        "ticket_form.html",
        page_title=f"{ticket_key} 편집",
        active="tickets",
        project=project,
        mode="edit",
        ticket=ticket,
        members=MEMBERS,
    )


@router.get(
    "/projects/{project_key}/tickets/{ticket_key}",
    response_class=HTMLResponse,
)
def ticket_detail(request: Request, project_key: str, ticket_key: str) -> HTMLResponse:
    project = _project(project_key)
    ticket = _ticket(project_key, ticket_key)
    return _render(
        request,
        "ticket_detail.html",
        page_title=f"{ticket_key} · {ticket['title']}",
        active="tickets",
        project=project,
        ticket=ticket,
    )


@router.get("/projects/{project_key}/board", response_class=HTMLResponse)
def board(request: Request, project_key: str) -> HTMLResponse:
    project = _project(project_key)
    project_tickets = [item for item in TICKETS if item["project_key"] == project_key]
    columns = [
        {"code": "todo", "label": "등록"},
        {"code": "progress", "label": "진행중"},
        {"code": "hold", "label": "보류"},
        {"code": "done", "label": "완료"},
        {"code": "cancelled", "label": "취소"},
    ]
    return _render(
        request,
        "board.html",
        page_title=f"{project['name']} · 칸반",
        active="board",
        project=project,
        tickets=project_tickets,
        columns=columns,
    )


@router.get("/projects/{project_key}/settings", response_class=HTMLResponse)
def project_settings(request: Request, project_key: str) -> HTMLResponse:
    project = _project(project_key)
    return _render(
        request,
        "project_settings.html",
        page_title=f"{project['name']} · 설정",
        active="project-settings",
        project=project,
    )


@router.get("/projects/{project_key}/members", response_class=HTMLResponse)
def project_members(request: Request, project_key: str) -> HTMLResponse:
    project = _project(project_key)
    return _render(
        request,
        "project_members.html",
        page_title=f"{project['name']} · 구성원",
        active="project-members",
        project=project,
        members=MEMBERS,
    )


@router.get("/projects/{project_key}/trash", response_class=HTMLResponse)
def project_trash(request: Request, project_key: str) -> HTMLResponse:
    project = _project(project_key)
    return _render(
        request,
        "trash.html",
        page_title=f"{project['name']} · 휴지통",
        active="trash",
        project=project,
        trash_tickets=TRASH_TICKETS,
    )


@router.get("/admin/users", response_class=HTMLResponse, dependencies=[Depends(require_web_admin)])
def admin_users(request: Request) -> HTMLResponse:
    return _render(
        request,
        "admin_users.html",
        page_title="사용자 관리",
        active="admin-users",
        users=USERS,
    )


@router.get(
    "/admin/organizations", response_class=HTMLResponse, dependencies=[Depends(require_web_admin)]
)
def admin_organizations(request: Request) -> HTMLResponse:
    return _render(
        request,
        "admin_organizations.html",
        page_title="조직 관리",
        active="admin-organizations",
        organization_tree=ORGANIZATION_TREE,
    )


@router.get(
    "/admin/projects", response_class=HTMLResponse, dependencies=[Depends(require_web_admin)]
)
def admin_projects(request: Request) -> HTMLResponse:
    return _render(
        request,
        "admin_projects.html",
        page_title="전체 프로젝트 관리",
        active="admin-projects",
    )
