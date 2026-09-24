"""Cookie, CSRF and redirect rules shared by HTML and cookie-authenticated APIs."""

import hashlib
import hmac
import re
import secrets
from typing import Annotated
from urllib.parse import unquote, urlencode, urlsplit

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.domain.auth import AuthError, Identity
from app.services.auth import get_current_identity


def normalize_return_path(value: str | None) -> str:
    """return path 값을 정규화한다."""
    if not value or not value.startswith("/") or len(value) > 2048:
        return "/"
    decoded = value
    for _ in range(3):
        decoded = unquote(decoded)
    if (
        not decoded.startswith("/")
        or decoded.startswith("//")
        or "\\" in decoded
        or any(ord(char) < 32 or ord(char) == 127 for char in decoded)
    ):
        return "/"
    parsed = urlsplit(decoded)
    if (
        parsed.scheme
        or parsed.netloc
        or any(part in {".", ".."} for part in parsed.path.split("/"))
    ):
        return "/"
    if not (
        parsed.path in {"/", "/dashboard", "/projects"}
        or parsed.path.startswith(("/projects/", "/admin/"))
    ):
        return "/"
    return value


def build_login_url(next_path: str = "/", *, changed: bool = False) -> str:
    """로그인 url 구성한다."""
    query = {"next": normalize_return_path(next_path)}
    if changed:
        query["changed"] = "1"
    return "/login?" + urlencode(query)


def build_password_change_url(next_path: str = "/") -> str:
    """비밀번호 change url 구성한다."""
    return "/account/password?" + urlencode({"next": normalize_return_path(next_path)})


def get_optional_identity(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Identity | None:
    """optional identity 정보를 조회한다."""
    identity = get_current_identity(session, request.cookies.get(settings.session.cookie_name))
    request.state.current_user = identity
    return identity


def require_web_user(
    request: Request, identity: Annotated[Identity | None, Depends(get_optional_identity)]
) -> Identity:
    """web 사용자 필수 조건을 검증한다."""
    next_path = request.url.path + ("?" + request.url.query if request.url.query else "")
    if identity is None:
        raise HTTPException(303, headers={"Location": build_login_url(next_path)})
    if identity.must_change_password:
        raise HTTPException(303, headers={"Location": build_password_change_url(next_path)})
    return identity


def require_web_admin(identity: Annotated[Identity, Depends(require_web_user)]) -> Identity:
    """web 관리자 필수 조건을 검증한다."""
    if not identity.is_admin:
        raise HTTPException(403, detail="시스템 관리자 권한이 필요합니다.")
    return identity


def require_identity(
    identity: Annotated[Identity | None, Depends(get_optional_identity)]
) -> Identity:
    """identity 필수 조건을 검증한다."""
    if identity is None:
        raise AuthError("authentication_required", "로그인이 필요합니다.", 401)
    return identity


def require_api_user(identity: Annotated[Identity, Depends(require_identity)]) -> Identity:
    """API 사용자 필수 조건을 검증한다."""
    if identity.must_change_password:
        raise AuthError("password_change_required", "비밀번호를 먼저 변경하세요.", 403)
    return identity


def require_api_admin(identity: Annotated[Identity, Depends(require_api_user)]) -> Identity:
    """API 관리자 필수 조건을 검증한다."""
    if not identity.is_admin:
        raise AuthError("admin_required", "시스템 관리자 권한이 필요합니다.", 403)
    return identity


def get_csrf_cookie_name(settings: Settings) -> str:
    """CSRF cookie name 정보를 조회한다."""
    return settings.session.cookie_name + "_csrf"


def create_session_csrf_token(token: str) -> str:
    """session CSRF token 생성을 처리한다."""
    return hmac.new(token.encode("utf-8"), b"taskflow-csrf-v1", hashlib.sha256).hexdigest()


def create_page_csrf_token(
    request: Request, response: Response, identity: Identity | None, settings: Settings
) -> str:
    """화면 CSRF token 생성을 처리한다."""
    if identity:
        return create_session_csrf_token(request.cookies[settings.session.cookie_name])
    token = request.cookies.get(get_csrf_cookie_name(settings), "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        token = secrets.token_urlsafe(32)
    response.set_cookie(
        get_csrf_cookie_name(settings),
        token,
        max_age=settings.auth.csrf_lifetime_minutes * 60,
        httponly=True,
        secure=settings.session.cookie_secure,
        samesite="strict",
        path="/",
    )
    return token


def _parse_request_origin(value: str) -> tuple[str, str, int] | None:
    """요청 origin을 비교 가능한 구조로 해석한다."""
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            return None
        return (
            parsed.scheme,
            parsed.hostname.lower(),
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )
    except ValueError:
        return None


def verify_csrf(
    request: Request, submitted: str, identity: Identity | None, settings: Settings
) -> None:
    """CSRF 검증한다."""
    supplied_origin = request.headers.get("origin")
    if supplied_origin is None:
        supplied_origin = request.headers.get("referer", "")
    expected_origin = settings.auth.public_origin or str(request.base_url)
    supplied_origin_parts = _parse_request_origin(supplied_origin)
    expected_origin_parts = _parse_request_origin(expected_origin)
    same_origin = (
        supplied_origin_parts is not None
        and supplied_origin_parts == expected_origin_parts
    )
    if not same_origin or request.headers.get("sec-fetch-site") == "cross-site":
        raise AuthError(
            "csrf_rejected",
            "요청을 확인할 수 없습니다. 페이지를 새로고침하고 다시 시도하세요.",
            403,
        )
    expected = (
        create_session_csrf_token(request.cookies[settings.session.cookie_name])
        if identity
        else request.cookies.get(get_csrf_cookie_name(settings), "")
    )
    if (
        not submitted
        or not expected
        or len(submitted) > 128
        or not hmac.compare_digest(submitted.encode("utf-8"), expected.encode("utf-8"))
    ):
        raise AuthError(
            "csrf_rejected",
            "요청을 확인할 수 없습니다. 페이지를 새로고침하고 다시 시도하세요.",
            403,
        )


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    """session cookie 설정한다."""
    response.set_cookie(
        settings.session.cookie_name,
        token,
        max_age=settings.session.lifetime_minutes * 60,
        path="/",
        httponly=True,
        secure=settings.session.cookie_secure,
        samesite=settings.session.cookie_samesite,
    )
    response.delete_cookie(get_csrf_cookie_name(settings), path="/")


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    """인증 cookies 제거한다."""
    response.delete_cookie(
        settings.session.cookie_name,
        path="/",
        secure=settings.session.cookie_secure,
        httponly=True,
        samesite=settings.session.cookie_samesite,
    )
    response.delete_cookie(
        get_csrf_cookie_name(settings),
        path="/",
        secure=settings.session.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def get_client_ip_address(request: Request) -> str:
    """client ip address 정보를 조회한다."""
    return (request.client.host if request.client else "unknown")[:45]
