from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import Identity
from app.services import auth as service
from app.web.security import (
    clear_auth_cookies,
    create_page_csrf_token,
    get_client_ip_address,
    get_optional_identity,
    normalize_return_path,
    require_identity,
    set_session_cookie,
    verify_csrf,
)

router = APIRouter(prefix="/api/auth", tags=["authentication"])
Database = Annotated[Session, Depends(get_db_session)]
OptionalIdentity = Annotated[Identity | None, Depends(get_optional_identity)]
RequiredIdentity = Annotated[Identity, Depends(require_identity)]


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login_id: str = Field(max_length=100)
    password: SecretStr = Field(max_length=128)
    next: str = "/"


class PasswordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: SecretStr = Field(max_length=128)
    new_password: SecretStr = Field(max_length=128)
    confirmation: SecretStr = Field(max_length=128)


@router.get("/csrf")
def get_csrf_token(request: Request, identity: OptionalIdentity):
    temporary = JSONResponse({})
    token = create_page_csrf_token(request, temporary, identity, get_settings())
    response = JSONResponse({"csrf_token": token})
    for key, value in temporary.raw_headers:
        if key == b"set-cookie":
            response.raw_headers.append((key, value))
    return response


@router.get("/me")
def get_current_user(identity: RequiredIdentity):
    return {
        "id": identity.id,
        "login_id": identity.login_id,
        "display_name": identity.display_name,
        "system_role": identity.system_role,
        "must_change_password": identity.must_change_password,
    }


@router.post("/login")
def login(request: Request, payload: LoginInput, session: Database, identity: OptionalIdentity):
    settings = get_settings()
    verify_csrf(request, request.headers.get("x-csrf-token", ""), identity, settings)
    token, user = service.authenticate_user(
        session,
        settings,
        payload.login_id,
        payload.password.get_secret_value(),
        get_client_ip_address(request),
        request.cookies.get(settings.session.cookie_name),
    )
    response = JSONResponse(
        {
            "must_change_password": user.must_change_password,
            "next": normalize_return_path(payload.next),
        }
    )
    set_session_cookie(response, token, settings)
    return response


@router.post("/password")
def change_current_user_password(
    request: Request, payload: PasswordInput, session: Database, identity: RequiredIdentity
):
    settings = get_settings()
    verify_csrf(request, request.headers.get("x-csrf-token", ""), identity, settings)
    service.change_user_password(
        session,
        settings,
        identity,
        payload.current_password.get_secret_value(),
        payload.new_password.get_secret_value(),
        payload.confirmation.get_secret_value(),
        get_client_ip_address(request),
    )
    response = JSONResponse({"reauthentication_required": True})
    clear_auth_cookies(response, settings)
    return response


@router.post("/logout")
def logout(request: Request, session: Database, identity: RequiredIdentity):
    settings = get_settings()
    verify_csrf(request, request.headers.get("x-csrf-token", ""), identity, settings)
    service.logout_user(
        session,
        identity,
        request.cookies[settings.session.cookie_name],
        get_client_ip_address(request),
    )
    response = JSONResponse({"logged_out": True})
    clear_auth_cookies(response, settings)
    return response
