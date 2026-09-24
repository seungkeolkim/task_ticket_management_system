import logging
import re
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.types import utc_now
from app.domain.auth import hash_password, token_digest
from app.main import app
from app.models import AuditLog, Organization, User, UserSession

INITIAL_PASSWORD = "Initial-password-123"
NEW_PASSWORD = "Changed-password-456"
ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture
def account(db_session: Session) -> User:
    """인증 테스트용 사용자 계정을 생성한다."""
    org = Organization(key="auth-test", name="테스트 조직")
    db_session.add(org)
    db_session.flush()
    user = User(
        login_id="tester",
        display_name="실제 사용자",
        organization_id=org.id,
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def form_token(response) -> str:
    """로그인 form의 CSRF token을 읽는다."""
    return re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)


def api_login(client: TestClient, password: str = INITIAL_PASSWORD, login_id: str = "tester"):
    """인증 API로 테스트 사용자를 로그인시킨다."""
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    return client.post(
        "/api/auth/login",
        json={"login_id": login_id, "password": password},
        headers=ORIGIN | {"X-CSRF-Token": csrf},
    )


def test_first_login_change_relogin_and_logout(
    client: TestClient, account: User, db_session: Session
):
    """로그인 관련 동작을 검증한다."""
    original = "/projects/OPS/tickets?selected=OPS-142"
    redirect = client.get(original, follow_redirects=False)
    assert redirect.status_code == 303
    assert parse_qs(urlsplit(redirect.headers["location"]).query)["next"] == [original]
    login_page = client.get(redirect.headers["location"])
    assert 'action="/login" method="post"' in login_page.text
    assert "mock-password" not in login_page.text
    assert "인증 없이" not in login_page.text
    result = client.post(
        "/login",
        data={
            "login_id": " TESTER ",
            "password": INITIAL_PASSWORD,
            "csrf_token": form_token(login_page),
            "next": original,
        },
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert result.status_code == 303
    assert result.headers["location"].startswith("/account/password?")
    token = client.cookies.get(get_settings().session.cookie_name)
    stored = db_session.scalar(select(UserSession))
    assert stored.token_hash == token_digest(token) and stored.token_hash != token
    cookie = result.headers.get_list("set-cookie")[0].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert INITIAL_PASSWORD not in result.headers["location"]
    assert (
        client.get("/", follow_redirects=False).headers["location"].startswith("/account/password?")
    )
    password_page = client.get(result.headers["location"])
    assert "내 작업으로 돌아가기" not in password_page.text
    changed = client.post(
        "/account/password",
        data={
            "current_password": INITIAL_PASSWORD,
            "new_password": NEW_PASSWORD,
            "confirmation": NEW_PASSWORD,
            "csrf_token": form_token(password_page),
            "next": original,
        },
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert changed.status_code == 303 and "changed=1" in changed.headers["location"]
    assert client.get("/api/auth/me").status_code == 401
    assert db_session.scalar(select(func.count()).select_from(UserSession)) == 0
    db_session.refresh(account)
    assert not account.must_change_password
    assert "새 비밀번호로 로그인" in client.get(changed.headers["location"]).text
    page = client.get(changed.headers["location"])
    final_login = client.post(
        "/login",
        data={
            "login_id": "tester",
            "password": NEW_PASSWORD,
            "csrf_token": form_token(page),
            "next": original,
        },
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert final_login.headers["location"] == original
    home = client.get("/")
    assert "실제 사용자" in home.text and "테스트 조직" in home.text
    assert 'href="/admin/users"' not in home.text
    assert home.headers["cache-control"] == "no-store"
    assert client.get("/admin/users").status_code == 403
    out = client.post(
        "/logout", data={"csrf_token": form_token(home)}, headers=ORIGIN, follow_redirects=False
    )
    assert out.headers["location"] == "/login"
    assert client.get("/api/auth/me").status_code == 401
    actions = set(db_session.scalars(select(AuditLog.action)))
    assert {"auth.login_succeeded", "auth.password_changed", "auth.logout"} <= actions


@pytest.mark.parametrize("path", ["/", "/projects", "/projects/OPS/board", "/admin/users"])
def test_no_protected_html_without_login(client: TestClient, path: str):
    """로그인·HTML 관련 동작을 검증한다."""
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?")
    assert response.headers["cache-control"] == "no-store"


def test_logged_in_login_page_returns_to_destination(
    client: TestClient, account: User, db_session: Session
):
    """로그인 관련 동작을 검증한다."""
    account.must_change_password = False
    db_session.commit()
    assert api_login(client).status_code == 200
    assert (
        client.get("/login?next=/projects", follow_redirects=False).headers["location"]
        == "/projects"
    )
    assert client.get("/logout").status_code == 405


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "null"},
        {"Origin": "http://testserver.evil"},
        {"Origin": "http://testserver:81"},
        {"Origin": "https://testserver"},
        {"Origin": "http://testserver@evil.example"},
        {"Origin": "http://testserver", "Sec-Fetch-Site": "cross-site"},
    ],
)
def test_login_requires_exact_origin(client: TestClient, account: User, headers: dict):
    """로그인 관련 동작을 검증한다."""
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    result = client.post(
        "/api/auth/login",
        json={"login_id": "tester", "password": INITIAL_PASSWORD},
        headers=headers | {"X-CSRF-Token": csrf},
    )
    assert result.status_code == 403 and result.json()["code"] == "csrf_rejected"


def test_csrf_token_required_and_referer_fallback(client: TestClient, account: User):
    """CSRF 관련 동작을 검증한다."""
    page = client.get("/login")
    data = {"login_id": "tester", "password": INITIAL_PASSWORD}
    assert client.post("/login", data=data, headers=ORIGIN).status_code == 403
    result = client.post(
        "/login",
        data=data | {"csrf_token": form_token(page)},
        headers={"Referer": "http://testserver/login"},
        follow_redirects=False,
    )
    assert result.status_code == 303
    assert (
        client.post("/logout", data={"csrf_token": form_token(page)}, headers=ORIGIN).status_code
        == 403
    )


def test_password_change_revokes_all_sessions_and_csrf_is_session_bound(
    client: TestClient,
    account: User,
    db_session: Session,
):
    """비밀번호·session·CSRF 관련 동작을 검증한다."""
    assert api_login(client).status_code == 200
    with TestClient(app) as second:
        assert api_login(second).status_code == 200
        first_csrf = client.get("/api/auth/csrf").json()["csrf_token"]
        second_csrf = second.get("/api/auth/csrf").json()["csrf_token"]
        assert first_csrf != second_csrf
        payload = {
            "current_password": INITIAL_PASSWORD,
            "new_password": NEW_PASSWORD,
            "confirmation": NEW_PASSWORD,
        }
        assert (
            second.post(
                "/api/auth/password", json=payload, headers=ORIGIN | {"X-CSRF-Token": first_csrf}
            ).status_code
            == 403
        )
        changed = client.post(
            "/api/auth/password", json=payload, headers=ORIGIN | {"X-CSRF-Token": first_csrf}
        )
        assert changed.status_code == 200 and changed.json()["reauthentication_required"]
        assert second.get("/api/auth/me").status_code == 401
    assert db_session.scalar(select(func.count()).select_from(UserSession)) == 0
    assert api_login(client, INITIAL_PASSWORD).status_code == 401
    assert api_login(client, NEW_PASSWORD).status_code == 200


@pytest.mark.parametrize("change", ["expired", "revoked", "inactive"])
def test_unusable_session_is_rejected(
    client: TestClient, account: User, db_session: Session, change: str
):
    """session 관련 동작을 검증한다."""
    assert api_login(client).status_code == 200
    stored = db_session.scalar(select(UserSession))
    if change == "expired":
        stored.expires_at = utc_now() - timedelta(seconds=1)
    elif change == "revoked":
        stored.revoked_at = utc_now()
    else:
        account.is_active = False
    db_session.commit()
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/", follow_redirects=False).headers["location"].startswith("/login?")
    if change == "inactive":
        assert api_login(client).status_code == 401


def test_failure_throttle_is_shared_by_clients_and_expires(
    client: TestClient,
    account: User,
    monkeypatch: pytest.MonkeyPatch,
):
    """client 간 로그인 실패 제한 공유와 만료를 검증한다."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "login_max_failures", 2)
    assert api_login(client, "wrong-password").status_code == 401
    assert api_login(client, "wrong-password").status_code == 401
    with TestClient(app) as second:
        limited = api_login(second)
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "900"
    monkeypatch.setattr("app.services.auth.utc_now", lambda: utc_now() + timedelta(seconds=901))
    assert api_login(client).status_code == 200


def test_ip_throttle_covers_unknown_login_ids(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """로그인 관련 동작을 검증한다."""
    monkeypatch.setattr(get_settings().auth, "login_max_ip_failures", 2)
    assert api_login(client, login_id="missing-a").status_code == 401
    assert api_login(client, login_id="missing-b").status_code == 401
    assert api_login(client, login_id="missing-c").status_code == 429


def test_errors_and_logs_do_not_echo_credentials(client: TestClient, account: User, caplog):
    """오류 응답과 로그에 인증 정보가 노출되지 않는지 검증한다."""
    root = logging.getLogger()
    root.addHandler(caplog.handler)
    try:
        secret = "Never-echo-this-password"
        failed = api_login(client, password=secret)
        assert failed.status_code == 401 and secret not in failed.text
        csrf = client.get("/api/auth/csrf").json()["csrf_token"]
        invalid = client.post(
            "/api/auth/login",
            json={"login_id": "tester", "password": secret * 20},
            headers=ORIGIN | {"X-CSRF-Token": csrf},
        )
        assert invalid.status_code == 422 and secret not in invalid.text
        assert secret not in caplog.text and csrf not in caplog.text
        assert account.password_hash not in caplog.text
    finally:
        root.removeHandler(caplog.handler)


def test_invalid_new_password_preserves_session_and_password(
    client: TestClient, account: User, db_session: Session
):
    """비밀번호·session 관련 동작을 검증한다."""
    old_hash = account.password_hash
    assert api_login(client).status_code == 200
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    for new_password, confirmation in (
        ("short", "short"),
        (INITIAL_PASSWORD, INITIAL_PASSWORD),
        (NEW_PASSWORD, "mismatch"),
    ):
        result = client.post(
            "/api/auth/password",
            json={
                "current_password": INITIAL_PASSWORD,
                "new_password": new_password,
                "confirmation": confirmation,
            },
            headers=ORIGIN | {"X-CSRF-Token": csrf},
        )
        assert result.status_code == 400
    db_session.refresh(account)
    assert account.password_hash == old_hash and account.must_change_password
    assert client.get("/api/auth/me").status_code == 200


def test_https_public_origin_and_secure_cookie(client: TestClient, account: User, monkeypatch):
    """HTTPS 공개 origin과 Secure cookie 설정을 검증한다."""
    settings = get_settings()
    monkeypatch.setattr(settings.session, "cookie_secure", True)
    monkeypatch.setattr(settings.auth, "public_origin", "https://tasks.example.test")
    with TestClient(app, base_url="https://tasks.example.test") as browser:
        csrf = browser.get("/api/auth/csrf").json()["csrf_token"]
        response = browser.post(
            "/api/auth/login",
            json={"login_id": "tester", "password": INITIAL_PASSWORD},
            headers={"Origin": "https://tasks.example.test", "X-CSRF-Token": csrf},
        )
        assert response.status_code == 200
        cookie = response.headers.get_list("set-cookie")[0].lower()
        assert "secure" in cookie and "httponly" in cookie and "domain=" not in cookie
        assert browser.get("/api/auth/me").status_code == 200
