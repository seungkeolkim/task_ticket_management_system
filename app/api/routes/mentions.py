"""멘션 후보 검색과 본인 멘션 읽음 API."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import Identity
from app.services import mentions as service
from app.web.security import require_api_user, verify_csrf

router = APIRouter(tags=["mentions"])
Database = Annotated[Session, Depends(get_db_session)]
Actor = Annotated[Identity, Depends(require_api_user)]


@router.get("/api/projects/{project_key}/mention-candidates")
def mention_candidates(
    project_key: str,
    session: Database,
    actor: Actor,
    query: str = Query(default="", max_length=100),
):
    """최대 50명의 활성 프로젝트 구성원 후보를 조회한다."""
    return service.list_candidates(session, actor, project_key, query)


@router.post("/api/mentions/read-all")
def read_all_mentions(request: Request, session: Database, actor: Actor):
    """현재 읽을 수 있는 본인 미확인 멘션을 전부 확인한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.mark_read(session, actor)


@router.post("/api/mentions/{mention_id}/read")
def read_mention(mention_id: int, request: Request, session: Database, actor: Actor):
    """개별 멘션을 확인하고 원본 이동 경로를 반환한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.mark_read(session, actor, mention_id)
