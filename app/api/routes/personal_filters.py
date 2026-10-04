from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import Identity
from app.schemas.personal_filters import (
    PersonalFilterCreate,
    PersonalFilterDelete,
    PersonalFilterSummary,
    PersonalFilterUpdate,
    PersonalFilterView,
)
from app.services import personal_filters as service
from app.web.security import require_api_user, verify_csrf

router = APIRouter(prefix="/api/projects/{project_key}/personal-filters", tags=["personal-filters"])
Database = Annotated[Session, Depends(get_db_session)]
Actor = Annotated[Identity, Depends(require_api_user)]


@router.get("", response_model=list[PersonalFilterSummary])
def list_personal_filters_api(project_key: str, session: Database, actor: Actor):
    """현재 프로젝트의 본인 전용 필터 목록을 반환한다."""
    return service.list_personal_filters(session, actor, project_key)


@router.get("/{filter_id}", response_model=PersonalFilterView)
def get_personal_filter_api(project_key: str, filter_id: int, session: Database, actor: Actor):
    """소유자·프로젝트·조건을 재검증한 개인 필터를 반환한다."""
    return service.get_personal_filter(session, actor, project_key, filter_id)


@router.post("", response_model=PersonalFilterSummary, status_code=201)
def create_personal_filter_api(
    project_key: str,
    request: Request,
    payload: PersonalFilterCreate,
    session: Database,
    actor: Actor,
):
    """CSRF 검증 후 개인 필터를 생성한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.create_personal_filter(session, actor, project_key, payload)


@router.patch("/{filter_id}", response_model=PersonalFilterSummary)
def update_personal_filter_api(
    project_key: str,
    filter_id: int,
    request: Request,
    payload: PersonalFilterUpdate,
    session: Database,
    actor: Actor,
):
    """본인 필터의 이름 또는 조건을 CSRF·동시 수정 검증 후 변경한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.update_personal_filter(session, actor, project_key, filter_id, payload)


@router.delete("/{filter_id}", status_code=204)
def delete_personal_filter_api(
    project_key: str,
    filter_id: int,
    request: Request,
    payload: PersonalFilterDelete,
    session: Database,
    actor: Actor,
):
    """CSRF·동시 수정 검증 후 본인 필터를 삭제한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    service.delete_personal_filter(session, actor, project_key, filter_id, payload)
    return Response(status_code=204)
