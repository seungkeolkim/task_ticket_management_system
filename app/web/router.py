from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.web.mock_data import (
    MENTIONS,
    PROJECTS,
    TICKETS,
)
from app.web.rendering import STATIC_DIRECTORY, render  # noqa: F401
from app.web.security import require_web_user

router = APIRouter(include_in_schema=False, dependencies=[Depends(require_web_user)])


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
