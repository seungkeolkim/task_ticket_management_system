from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.domain.auth import AuthError, hash_password, normalize_login_id, verify_password
from app.models import AuditLog, Organization, User
from app.services.auth import authenticate_user
from app.services.bootstrap import bootstrap_admin, bootstrap_from_environment
from app.web.security import normalize_return_path


def test_argon2id_and_password_policy():
    password = "한글을 포함하는 긴 비밀번호123"
    first = hash_password(password)
    second = hash_password(password)
    assert first.startswith("$argon2id$") and first != second
    assert verify_password(password, first)
    assert not verify_password("incorrect-password", first)
    assert not verify_password(password, "malformed-hash")
    assert not verify_password(password, None)
    for invalid in ("short", " " * 12, "a" * 129, "password-with\nnewline"):
        with pytest.raises(AuthError):
            hash_password(invalid)


def test_login_id_normalization():
    assert normalize_login_id(" Admin.Test-1 ") == "admin.test-1"
    for invalid in ("ab", "한글아이디", "admin@test", "-admin", "a" * 101):
        with pytest.raises(AuthError):
            normalize_login_id(invalid)


@pytest.mark.parametrize(
    "path",
    [
        "https://evil.example",
        "//evil.example",
        "/%2fexample.com",
        "/%5cevil.com",
        "/\\evil.com",
        "/projects/../../evil",
        "/login",
        "/account/password",
        "/api/auth/logout",
        "/projects\r\nLocation: https://evil.com",
        "/%252fexample.com",
        "%2Fprojects",
    ],
)
def test_redirect_rejects_external_ambiguous_and_auth_targets(path: str):
    assert normalize_return_path(path) == "/"


def test_redirect_preserves_internal_query():
    assert (
        normalize_return_path("/projects/OPS/tickets?selected=OPS-142")
        == "/projects/OPS/tickets?selected=OPS-142"
    )


def test_bootstrap_is_atomic_and_idempotent(db_session_factory):
    settings = Settings()
    first = bootstrap_admin(
        db_session_factory, settings, "Initial.Admin", "Bootstrap-password-123", "관리자"
    )
    assert first is not None
    assert bootstrap_admin(db_session_factory, settings, "bad", "invalid", "") is None
    with db_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        user = session.get(User, first)
        assert user.login_id == "initial.admin" and user.must_change_password
        assert user.system_role == "SYSTEM_ADMIN" and verify_password(
            "Bootstrap-password-123", user.password_hash
        )
        assert session.scalar(select(Organization)).name == "기본 조직"
        assert session.scalar(select(AuditLog)).action == "auth.bootstrap_admin_created"


def test_concurrent_bootstrap_creates_one_admin(db_session_factory):
    def create(login_id):
        return bootstrap_admin(
            db_session_factory, Settings(), login_id, "Bootstrap-password-123", "관리자"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(create, ["admin.one", "admin.two"]))
    assert sum(value is not None for value in ids) == 1
    with db_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(Organization)) == 1


def test_invalid_bootstrap_does_not_leave_an_organization(db_session_factory):
    with pytest.raises(AuthError):
        bootstrap_admin(db_session_factory, Settings(), "admin", "short", "관리자")
    with db_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Organization)) == 0


def test_environment_bootstrap_secret_file_and_existing_user_skip(
    db_session_factory, tmp_path, monkeypatch
):
    secret_file = tmp_path / "password.secret"
    secret_file.write_text("Bootstrap-password-123\n", encoding="utf-8")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_LOGIN_ID", "env.admin")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD_FILE", str(secret_file))
    bootstrap_from_environment(db_session_factory, Settings())
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD_FILE", "missing-secret-file")
    bootstrap_from_environment(db_session_factory, Settings())
    with db_session_factory() as session:
        assert session.scalar(select(User)).login_id == "env.admin"


def test_environment_bootstrap_partial_configuration_fails(db_session_factory, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_LOGIN_ID", "admin")
    with pytest.raises(ValueError, match="requires"):
        bootstrap_from_environment(db_session_factory, Settings())


def test_concurrent_failures_obey_the_configured_limit(db_session_factory):
    settings = Settings()
    settings.auth.login_max_failures = 2
    bootstrap_admin(db_session_factory, settings, "admin", "Bootstrap-password-123", "관리자")

    def attempt(_):
        with db_session_factory() as session:
            try:
                authenticate_user(session, settings, "admin", "wrong-password", "127.0.0.1")
            except AuthError as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(attempt, range(4)))
    assert sorted(statuses) == [401, 401, 429, 429]
