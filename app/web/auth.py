from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import AuthError, Identity
from app.repositories.auth import user_count
from app.services import auth as service
from app.web.rendering import render
from app.web.security import (
    clear_auth_cookies,
    client_ip,
    login_url,
    optional_identity,
    password_url,
    safe_return_path,
    set_session_cookie,
    verify_csrf,
)

router = APIRouter(include_in_schema=False)
Database = Annotated[Session, Depends(get_db_session)]
OptionalIdentity = Annotated[Identity | None, Depends(optional_identity)]


@router.get("/login")
def login_page(
    request: Request,
    session: Database,
    identity: OptionalIdentity,
    next: str = "/",
    changed: str = "",
):
    destination = safe_return_path(next)
    if identity:
        return RedirectResponse(
            password_url(destination) if identity.must_change_password else destination,
            status_code=303,
        )
    response = render(
        request,
        "login.html",
        page_title="로그인",
        next_path=destination,
        changed=changed == "1",
        setup_required=user_count(session) == 0,
    )
    response.delete_cookie(get_settings().session.cookie_name, path="/")
    return response


@router.post("/login")
def login_submit(
    request: Request,
    session: Database,
    identity: OptionalIdentity,
    login_id: Annotated[str, Form()],
    password: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "/",
):
    settings = get_settings()
    verify_csrf(request, csrf_token, identity, settings)
    destination = safe_return_path(next)
    try:
        token, user = service.login(
            session,
            settings,
            login_id,
            password,
            client_ip(request),
            request.cookies.get(settings.session.cookie_name),
        )
    except AuthError as error:
        response = render(
            request,
            "login.html",
            page_title="로그인",
            next_path=destination,
            error=error.message,
            login_id=login_id[:100],
            status_code=error.status_code,
        )
        if error.retry_after:
            response.headers["Retry-After"] = str(error.retry_after)
        return response
    response = RedirectResponse(
        password_url(destination) if user.must_change_password else destination, status_code=303
    )
    set_session_cookie(response, token, settings)
    return response


@router.get("/account/password")
def password_page(request: Request, identity: OptionalIdentity, next: str = "/"):
    if identity is None:
        return RedirectResponse(login_url(next), status_code=303)
    return render(
        request, "password.html", page_title="비밀번호 변경", next_path=safe_return_path(next)
    )


@router.post("/account/password")
def password_submit(
    request: Request,
    session: Database,
    identity: OptionalIdentity,
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    confirmation: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "/",
):
    if identity is None:
        return RedirectResponse(login_url(next), status_code=303)
    settings = get_settings()
    verify_csrf(request, csrf_token, identity, settings)
    destination = safe_return_path(next)
    try:
        service.change_password(
            session,
            settings,
            identity,
            current_password,
            new_password,
            confirmation,
            client_ip(request),
        )
    except AuthError as error:
        response = render(
            request,
            "password.html",
            page_title="비밀번호 변경",
            next_path=destination,
            error=error.message,
            status_code=error.status_code,
        )
        if error.retry_after:
            response.headers["Retry-After"] = str(error.retry_after)
        return response
    response = RedirectResponse(login_url(destination, changed=True), status_code=303)
    clear_auth_cookies(response, settings)
    return response


@router.post("/logout")
def logout_submit(
    request: Request,
    session: Database,
    identity: OptionalIdentity,
    csrf_token: Annotated[str, Form()] = "",
):
    settings = get_settings()
    if identity:
        verify_csrf(request, csrf_token, identity, settings)
        service.logout(
            session, identity, request.cookies[settings.session.cookie_name], client_ip(request)
        )
    response = RedirectResponse("/login", status_code=303)
    clear_auth_cookies(response, settings)
    return response
