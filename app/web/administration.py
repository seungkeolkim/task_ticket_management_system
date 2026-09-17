from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import AuthError, Identity
from app.schemas.administration import OrganizationCreate, UserCreate
from app.services import administration as service
from app.web.rendering import render
from app.web.security import client_ip, require_web_admin, verify_csrf

router = APIRouter(include_in_schema=False)
Database = Annotated[Session, Depends(get_db_session)]
Administrator = Annotated[Identity, Depends(require_web_admin)]


def users_page(request, session, actor, *, q="", page=1, page_size=None, **context):
    result = service.user_list(session, actor, q, page, page_size)
    query = {"q": q, "page_size": result.page_size}
    return render(
        request,
        "admin_users.html",
        page_title="사용자 관리",
        active="admin-users",
        live_page=True,
        result=result,
        organizations=service.organization_list(session, actor),
        q=q,
        previous_url="/admin/users?" + urlencode(query | {"page": page - 1}),
        next_url="/admin/users?" + urlencode(query | {"page": page + 1}),
        **context,
    )


def organizations_page(request, session, actor, **context):
    return render(
        request,
        "admin_organizations.html",
        page_title="조직 관리",
        active="admin-organizations",
        live_page=True,
        organizations=service.organization_list(session, actor),
        **context,
    )


@router.get("/admin/users")
def users(
    request: Request,
    session: Database,
    actor: Administrator,
    q: str = "",
    page: int = 1,
    page_size: int | None = None,
    created: int | None = None,
):
    return users_page(request, session, actor, q=q, page=page, page_size=page_size, created=created)


@router.get("/admin/organizations")
def organizations(
    request: Request, session: Database, actor: Administrator, created: int | None = None
):
    return organizations_page(request, session, actor, created=created)


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
        row_id = service.create_user(session, actor, payload, client_ip(request))
    except ValidationError:
        return users_page(
            request,
            session,
            actor,
            values=values,
            error="입력 항목의 형식과 길이를 확인하세요. 비밀번호는 다시 입력해 주세요.",
            status_code=422,
        )
    except AuthError as error:
        return users_page(
            request,
            session,
            actor,
            values=values,
            error=error.message,
            status_code=error.status_code,
        )
    return RedirectResponse(f"/admin/users?created={row_id}", status_code=303)


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
    verify_csrf(request, csrf_token, actor, get_settings())
    values = dict(name=name[:200], parent_id=parent_id[:20], description=description[:4000])
    try:
        payload = OrganizationCreate(
            name=name, parent_id=parent_id or None, description=description
        )
        row_id = service.create_organization(session, actor, payload, client_ip(request))
    except ValidationError:
        return organizations_page(
            request,
            session,
            actor,
            values=values,
            error="조직명, 상위 조직과 설명의 형식·길이를 확인하세요.",
            status_code=422,
        )
    except AuthError as error:
        return organizations_page(
            request,
            session,
            actor,
            values=values,
            error=error.message,
            status_code=error.status_code,
        )
    return RedirectResponse(f"/admin/organizations?created={row_id}", status_code=303)
