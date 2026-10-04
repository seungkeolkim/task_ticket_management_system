from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import Identity
from app.services import dashboard as service
from app.services import mentions as mention_service
from app.web.rendering import STATIC_DIRECTORY, render  # noqa: F401
from app.web.security import require_web_user, verify_csrf

router = APIRouter(include_in_schema=False, dependencies=[Depends(require_web_user)])
Database = Annotated[Session, Depends(get_db_session)]
Actor = Annotated[Identity, Depends(require_web_user)]


@router.get("/", response_class=HTMLResponse)
def dashboard_page(request: Request, session: Database, actor: Actor) -> HTMLResponse:
    """내 작업 대시보드 화면을 렌더링한다."""
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
    """대시보드 별칭 경로를 기본 화면으로 redirect한다."""
    return RedirectResponse(url="/", status_code=307)


@router.post("/mentions/read-all")
def read_all_mentions_page(
    request: Request, session: Database, actor: Actor, csrf_token: str = Form(...)
):
    """전체 읽음 처리 후 최신 대시보드로 돌아간다."""
    verify_csrf(request, csrf_token, actor, get_settings())
    mention_service.mark_read(session, actor)
    return RedirectResponse("/", status_code=303)


@router.post("/mentions/{mention_id}/read")
def read_mention_page(
    mention_id: int,
    request: Request,
    session: Database,
    actor: Actor,
    csrf_token: str = Form(...),
    open_source: bool = Form(False),
):
    """개별 멘션을 확인하고 요청한 경우 원본 댓글 위치로 이동한다."""
    verify_csrf(request, csrf_token, actor, get_settings())
    result = mention_service.mark_read(session, actor, mention_id)
    return RedirectResponse(result["destination"] if open_source else "/", status_code=303)
