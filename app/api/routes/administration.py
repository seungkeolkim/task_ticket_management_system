from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import AuthError, Identity
from app.schemas.administration import (
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationView,
    UserCreate,
    UserPage,
    UserPasswordReset,
    UserUpdate,
    UserView,
)
from app.services import administration as service
from app.services import organization_transfer
from app.web.security import get_client_ip_address, require_api_admin, verify_csrf

router = APIRouter(prefix="/api/admin", tags=["administration"])
Database = Annotated[Session, Depends(get_db_session)]
Administrator = Annotated[Identity, Depends(require_api_admin)]


class OrganizationImportApply(BaseModel):
    """미리보기 후 적용할 JSON 원문과 token이다."""

    document_json: str = Field(max_length=organization_transfer.MAX_DOCUMENT_BYTES)
    preview_token: str = Field(min_length=64, max_length=64)


async def read_organization_import_body(request: Request) -> bytes:
    """API import 본문을 제한 크기까지만 읽는다."""
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > organization_transfer.MAX_DOCUMENT_BYTES:
            raise AuthError(
                "organization_import_too_large", "조직 JSON 파일은 16MB 이하여야 합니다.", 413
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.get("/users", response_model=UserPage)
def list_administrator_users(
    session: Database,
    actor: Administrator,
    search_query: Annotated[str, Query(alias="q")] = "",
    page: int = 1,
    page_size: int | None = None,
):
    """관리자 사용자 목록을 조회한다."""
    return service.list_users(session, actor, search_query, page, page_size)


@router.get("/organizations", response_model=list[OrganizationView])
def list_administrator_organizations(session: Database, actor: Administrator):
    """관리자 조직 목록을 조회한다."""
    return service.list_organizations(session, actor)


@router.post("/users", status_code=201)
def create_user(request: Request, payload: UserCreate, session: Database, actor: Administrator):
    """사용자 생성을 처리한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return {"id": service.create_user(session, actor, payload, get_client_ip_address(request))}


@router.patch("/users/{user_id}", response_model=UserView)
def update_user(
    user_id: int,
    request: Request,
    payload: UserUpdate,
    session: Database,
    actor: Administrator,
):
    """관리자 사용자 수정을 처리한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.update_user(session, actor, user_id, payload, get_client_ip_address(request))


@router.post("/users/{user_id}/password-reset", response_model=UserView)
def reset_user_password(
    user_id: int,
    request: Request,
    payload: UserPasswordReset,
    session: Database,
    actor: Administrator,
):
    """관리자 사용자 임시 비밀번호 설정을 처리한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.reset_user_password(
        session, actor, user_id, payload, get_client_ip_address(request)
    )


@router.post("/organizations", status_code=201)
def create_organization(
    request: Request, payload: OrganizationCreate, session: Database, actor: Administrator
):
    """조직 생성을 처리한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return {
        "id": service.create_organization(session, actor, payload, get_client_ip_address(request))
    }


@router.patch("/organizations/{organization_id}", response_model=OrganizationView)
def update_organization(
    organization_id: int,
    request: Request,
    payload: OrganizationUpdate,
    session: Database,
    actor: Administrator,
):
    """관리자 조직 수정을 처리한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.update_organization(
        session, actor, organization_id, payload, get_client_ip_address(request)
    )


@router.get("/organizations/export")
def export_organizations(session: Database, actor: Administrator):
    """전체 조직 계층 JSON을 다운로드한다."""
    document = organization_transfer.export_organization_document(session, actor)
    return Response(
        content=document,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="organizations.json"'},
    )


@router.post("/organizations/import/preview")
async def preview_organization_import(request: Request, session: Database, actor: Administrator):
    """업로드한 JSON의 적용 예정 변경과 충돌을 반환한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    document = await read_organization_import_body(request)
    session_token = request.cookies[get_settings().session.cookie_name]
    return organization_transfer.preview_organization_import(
        session, actor, document, session_token
    )


@router.post("/organizations/import/apply")
def apply_organization_import(
    request: Request,
    payload: OrganizationImportApply,
    session: Database,
    actor: Administrator,
):
    """확인된 조직 JSON을 전체 transaction으로 적용한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    session_token = request.cookies[get_settings().session.cookie_name]
    return organization_transfer.apply_organization_import(
        session,
        actor,
        payload.document_json.encode("utf-8"),
        session_token,
        payload.preview_token,
        get_client_ip_address(request),
    )
