from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import AuthError, Identity
from app.schemas.administration import (
    OrganizationCreate,
    OrganizationUpdate,
    UserCreate,
    UserPasswordReset,
    UserUpdate,
)
from app.services import administration as service
from app.services import organization_transfer
from app.web.rendering import render
from app.web.security import get_client_ip_address, require_web_admin, verify_csrf

router = APIRouter(include_in_schema=False)
Database = Annotated[Session, Depends(get_db_session)]
Administrator = Annotated[Identity, Depends(require_web_admin)]


def render_user_management_page(
    request, session, actor, *, search_query="", page=1, page_size=None, **context
):
    """사용자 management 화면 렌더링한다."""
    result = service.list_users(session, actor, search_query, page, page_size)
    query = {"q": search_query, "page_size": result.page_size}
    return render(
        request,
        "admin_users.html",
        page_title="사용자 관리",
        active="admin-users",
        live_page=True,
        result=result,
        organizations=service.list_organizations(session, actor),
        q=search_query,
        previous_url="/admin/users?" + urlencode(query | {"page": page - 1}),
        next_url="/admin/users?" + urlencode(query | {"page": page + 1}),
        **context,
    )


def render_organization_management_page(request, session, actor, **context):
    """조직 management 화면 렌더링한다."""
    return render(
        request,
        "admin_organizations.html",
        page_title="조직 관리",
        active="admin-organizations",
        live_page=True,
        organizations=service.list_organizations(session, actor),
        **context,
    )


@router.get("/admin/users")
def user_management_page(
    request: Request,
    session: Database,
    actor: Administrator,
    search_query: Annotated[str, Query(alias="q")] = "",
    page: int = 1,
    page_size: int | None = None,
    created: int | None = None,
    updated: int | None = None,
    password_reset: int | None = None,
):
    """사용자 관리 화면을 렌더링한다."""
    return render_user_management_page(
        request,
        session,
        actor,
        search_query=search_query,
        page=page,
        page_size=page_size,
        created=created,
        updated=updated,
        password_reset=password_reset,
    )


@router.get("/admin/organizations")
def organization_management_page(
    request: Request,
    session: Database,
    actor: Administrator,
    created: int | None = None,
    updated: int | None = None,
    imported: int | None = None,
):
    """조직 관리 화면을 렌더링한다."""
    return render_organization_management_page(
        request, session, actor, created=created, updated=updated, imported=imported
    )


@router.post("/admin/users")
def user_submit(
    request: Request,
    session: Database,
    actor: Administrator,
    login_id: Annotated[str, Form()] = "",
    display_name: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    organization_id: Annotated[str, Form()] = "",
    system_role: Annotated[str, Form()] = "USER",
    password: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """사용자 생성 form 제출을 처리한다."""
    verify_csrf(request, csrf_token, actor, get_settings())
    values = dict(
        login_id=login_id[:100],
        display_name=display_name[:200],
        email=email[:320],
        organization_id=organization_id[:20],
        system_role=system_role[:32],
    )
    try:
        payload = UserCreate(
            login_id=login_id,
            display_name=display_name,
            email=email,
            organization_id=organization_id,
            system_role=system_role,
            password=password,
        )
        row_id = service.create_user(session, actor, payload, get_client_ip_address(request))
    except ValidationError:
        return render_user_management_page(
            request,
            session,
            actor,
            values=values,
            error="입력 항목의 형식과 길이를 확인하세요. 비밀번호는 다시 입력해 주세요.",
            status_code=422,
        )
    except AuthError as error:
        return render_user_management_page(
            request,
            session,
            actor,
            values=values,
            error=error.message,
            status_code=error.status_code,
        )
    return RedirectResponse(f"/admin/users?created={row_id}", status_code=303)


@router.post("/admin/users/{user_id}/update")
def user_update_submit(
    user_id: int,
    request: Request,
    session: Database,
    actor: Administrator,
    display_name: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    organization_id: Annotated[str, Form()] = "",
    system_role: Annotated[str, Form()] = "USER",
    is_active: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """사용자 수정 form 제출을 처리한다."""
    verify_csrf(request, csrf_token, actor, get_settings())
    try:
        payload = UserUpdate(
            display_name=display_name,
            email=email,
            organization_id=organization_id,
            system_role=system_role,
            is_active=is_active == "true",
        )
        service.update_user(session, actor, user_id, payload, get_client_ip_address(request))
    except ValidationError:
        return render_user_management_page(
            request,
            session,
            actor,
            error="사용자 정보의 형식과 길이를 확인하세요.",
            status_code=422,
        )
    except AuthError as error:
        return render_user_management_page(
            request,
            session,
            actor,
            error=error.message,
            status_code=error.status_code,
        )
    return RedirectResponse(f"/admin/users?updated={user_id}", status_code=303)


@router.post("/admin/users/{user_id}/password-reset")
def user_password_reset_submit(
    user_id: int,
    request: Request,
    session: Database,
    actor: Administrator,
    temporary_password: Annotated[str, Form()] = "",
    confirmation: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """사용자 임시 비밀번호 설정 form 제출을 처리한다."""
    verify_csrf(request, csrf_token, actor, get_settings())
    try:
        payload = UserPasswordReset(
            temporary_password=temporary_password,
            confirmation=confirmation,
        )
        service.reset_user_password(
            session, actor, user_id, payload, get_client_ip_address(request)
        )
    except ValidationError:
        return render_user_management_page(
            request,
            session,
            actor,
            error="임시 비밀번호와 확인값을 확인하세요.",
            status_code=422,
        )
    except AuthError as error:
        return render_user_management_page(
            request,
            session,
            actor,
            error=error.message,
            status_code=error.status_code,
        )
    return RedirectResponse(f"/admin/users?password_reset={user_id}", status_code=303)


@router.post("/admin/organizations")
def organization_submit(
    request: Request,
    session: Database,
    actor: Administrator,
    name: Annotated[str, Form()] = "",
    parent_id: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """조직 생성 form 제출을 처리한다."""
    verify_csrf(request, csrf_token, actor, get_settings())
    values = dict(name=name[:200], parent_id=parent_id[:20], description=description[:4000])
    try:
        payload = OrganizationCreate(
            name=name, parent_id=parent_id or None, description=description
        )
        row_id = service.create_organization(
            session, actor, payload, get_client_ip_address(request)
        )
    except ValidationError:
        return render_organization_management_page(
            request,
            session,
            actor,
            values=values,
            error="조직명, 상위 조직과 설명의 형식·길이를 확인하세요.",
            status_code=422,
        )
    except AuthError as error:
        return render_organization_management_page(
            request,
            session,
            actor,
            values=values,
            error=error.message,
            status_code=error.status_code,
        )
    return RedirectResponse(f"/admin/organizations?created={row_id}", status_code=303)


@router.post("/admin/organizations/{organization_id}/update")
def organization_update_submit(
    organization_id: int,
    request: Request,
    session: Database,
    actor: Administrator,
    name: Annotated[str, Form()] = "",
    parent_id: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    is_active: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """조직 수정 form 제출을 처리한다."""
    verify_csrf(request, csrf_token, actor, get_settings())
    try:
        payload = OrganizationUpdate(
            name=name,
            parent_id=parent_id or None,
            description=description,
            is_active=is_active,
        )
        service.update_organization(
            session, actor, organization_id, payload, get_client_ip_address(request)
        )
    except ValidationError:
        return render_organization_management_page(
            request,
            session,
            actor,
            error="조직명, 상위 조직과 설명의 형식·길이를 확인하세요.",
            status_code=422,
        )
    except AuthError as error:
        return render_organization_management_page(
            request,
            session,
            actor,
            error=error.message,
            status_code=error.status_code,
        )
    return RedirectResponse(f"/admin/organizations?updated={organization_id}", status_code=303)


@router.get("/admin/organizations/export")
def organization_export(session: Database, actor: Administrator):
    """조직 계층 JSON 파일을 다운로드한다."""
    document = organization_transfer.export_organization_document(session, actor)
    return Response(
        content=document,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="organizations.json"'},
    )


@router.post("/admin/organizations/import/preview")
async def organization_import_preview_submit(
    request: Request,
    session: Database,
    actor: Administrator,
    document_file: Annotated[UploadFile, File()],
    csrf_token: Annotated[str, Form()] = "",
):
    """조직 JSON 파일을 읽고 추가·갱신·충돌 미리보기를 표시한다."""
    verify_csrf(request, csrf_token, actor, get_settings())
    document = await document_file.read(organization_transfer.MAX_DOCUMENT_BYTES + 1)
    await document_file.close()
    try:
        preview = organization_transfer.preview_organization_import(
            session,
            actor,
            document,
            request.cookies[get_settings().session.cookie_name],
        )
    except AuthError as error:
        return render_organization_management_page(
            request, session, actor, error=error.message, status_code=error.status_code
        )
    return render_organization_management_page(
        request,
        session,
        actor,
        preview=preview,
        preview_document=document.decode("utf-8-sig"),
    )


@router.post("/admin/organizations/import/apply")
def organization_import_apply_submit(
    request: Request,
    session: Database,
    actor: Administrator,
    document_json: Annotated[str, Form()] = "",
    preview_token: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """관리자가 미리보기 결과를 확인한 조직 JSON을 적용한다."""
    verify_csrf(request, csrf_token, actor, get_settings())
    try:
        result = organization_transfer.apply_organization_import(
            session,
            actor,
            document_json.encode("utf-8"),
            request.cookies[get_settings().session.cookie_name],
            preview_token,
            get_client_ip_address(request),
        )
    except AuthError as error:
        return render_organization_management_page(
            request, session, actor, error=error.message, status_code=error.status_code
        )
    return RedirectResponse(
        "/admin/organizations?imported=" + str(result["added"] + result["updated"]),
        status_code=303,
    )
