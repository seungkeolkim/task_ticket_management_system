from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.domain.auth import Identity
from app.services import dashboard as service
from app.web.rendering import STATIC_DIRECTORY, render  # noqa: F401
from app.web.security import require_web_user

router = APIRouter(include_in_schema=False, dependencies=[Depends(require_web_user)])
Database = Annotated[Session, Depends(get_db_session)]
Actor = Annotated[Identity, Depends(require_web_user)]


@router.get("/", response_class=HTMLResponse)
def dashboard_page(request: Request, session: Database, actor: Actor) -> HTMLResponse:
    result = service.get_dashboard(session, actor)
    return render(
        request,
        "dashboard.html",
        live_page=True,
        page_title="내 작업",
        active="dashboard",
        result=result,
    )


@router.get("/dashboard", include_in_schema=False)
def dashboard_alias() -> RedirectResponse:
    return RedirectResponse(url="/", status_code=307)
