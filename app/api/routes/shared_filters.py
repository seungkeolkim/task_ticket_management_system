from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import Identity
from app.schemas.shared_filters import (
    SharedFilterCreate,
    SharedFilterDelete,
    SharedFilterSummary,
    SharedFilterUpdate,
    SharedFilterView,
)
from app.services import shared_filters as service
from app.web.security import require_api_user, verify_csrf

router = APIRouter(prefix="/api/projects/{project_key}/shared-filters", tags=["shared-filters"])
Database = Annotated[Session, Depends(get_db_session)]
Actor = Annotated[Identity, Depends(require_api_user)]


@router.get("", response_model=list[SharedFilterSummary])
def list_shared_filters_api(project_key: str, session: Database, actor: Actor):
    """현재 프로젝트의 구성원 공용 필터 목록을 반환한다."""
    return service.list_shared_filters(session, actor, project_key)


@router.get("/{filter_id}", response_model=SharedFilterView)
def get_shared_filter_api(project_key: str, filter_id: int, session: Database, actor: Actor):
    """프로젝트·조건을 재검증한 공유 필터를 반환한다."""
    return service.get_shared_filter(session, actor, project_key, filter_id)


@router.post("", response_model=SharedFilterSummary, status_code=201)
def create_shared_filter_api(
    project_key: str,
    request: Request,
    payload: SharedFilterCreate,
    session: Database,
    actor: Actor,
):
    """CSRF 검증 후 공유 필터를 생성한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.create_shared_filter(session, actor, project_key, payload)


@router.patch("/{filter_id}", response_model=SharedFilterSummary)
def update_shared_filter_api(
    project_key: str,
    filter_id: int,
    request: Request,
    payload: SharedFilterUpdate,
    session: Database,
    actor: Actor,
):
    """공유 필터의 이름 또는 조건을 CSRF·동시 수정 검증 후 변경한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.update_shared_filter(session, actor, project_key, filter_id, payload)


@router.delete("/{filter_id}", status_code=204)
def delete_shared_filter_api(
    project_key: str,
    filter_id: int,
    request: Request,
    payload: SharedFilterDelete,
    session: Database,
    actor: Actor,
):
    """CSRF·동시 수정 검증 후 공유 필터를 삭제한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    service.delete_shared_filter(session, actor, project_key, filter_id, payload)
    return Response(status_code=204)
