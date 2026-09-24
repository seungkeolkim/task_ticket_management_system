import re
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.domain.auth import hash_password, verify_password
from app.main import app
from app.models import AuditLog, Organization, User
from app.schemas.administration import OrganizationCreate
from app.services import administration as service
from app.services.auth import get_current_identity

PASSWORD = "Disposable-admin-12345!"
ORIGIN = {"Origin": "http://testserver"}


def token(client):
    return client.get("/api/auth/csrf").json()["csrf_token"]


def post(client, path, payload):
    return client.post(path, json=payload, headers=ORIGIN | {"X-CSRF-Token": token(client)})


def login(client, login_id="admin", password=PASSWORD):
    return post(client, "/api/auth/login", {"login_id": login_id, "password": password})


@pytest.fixture
def admin(client, db_session):
    org = Organization(key="root", name="기본 조직")
    db_session.add(org)
    db_session.flush()
    account = User(
        login_id="admin",
        display_name="테스트 관리자",
        organization_id=org.id,
        system_role="SYSTEM_ADMIN",
        password_hash=hash_password(PASSWORD),
        must_change_password=False,
    )
    db_session.add(account)
    db_session.commit()
    assert login(client).status_code == 200
    return account


def new_user(default_organization_id, **overrides):
    return {
        "login_id": " New.User ",
        "display_name": " 새 사용자 ",
        "email": "",
        "organization_id": default_organization_id,
        "password": "New-user-pass-12345!",
        **overrides,
    }


def test_organization_user_and_first_login_flow(client, admin, db_session):
    root = post(client, "/api/admin/organizations", {"name": "개발 본부"})
    assert root.status_code == 201
    child = post(
        client,
        "/api/admin/organizations",
        {"name": "플랫폼팀", "parent_id": root.json()["id"], "description": "서비스 개발"},
    )
    assert child.status_code == 201
    created = post(client, "/api/admin/users", new_user(child.json()["id"]))
    assert created.status_code == 201
    user = db_session.get(User, created.json()["id"])
    assert user.login_id == "new.user" and user.display_name == "새 사용자"
    assert user.email is None and user.is_active and user.must_change_password
    assert verify_password("New-user-pass-12345!", user.password_hash)
    rows = client.get("/api/admin/organizations").json()
    team = next(row for row in rows if row["id"] == child.json()["id"])
    assert team["depth"] == 1 and team["member_count"] == 1
    assert "플랫폼팀" in client.get("/admin/users").text
    assert "서비스 개발" in client.get("/admin/organizations").text
    events = list(
        db_session.scalars(
            select(AuditLog).where(AuditLog.action.in_(["organization.created", "user.created"]))
        )
    )
    assert len(events) == 3 and all(event.actor_user_id == admin.id for event in events)
    assert events[-1].target_id == str(user.id)
    with TestClient(app) as newcomer:
        assert login(newcomer, "new.user", "New-user-pass-12345!").status_code == 200
        assert (
            newcomer.get("/", follow_redirects=False)
            .headers["location"]
            .startswith("/account/password")
        )
        changed = post(
            newcomer,
            "/api/auth/password",
            {
                "current_password": "New-user-pass-12345!",
                "new_password": "Changed-user-pass-12345!",
                "confirmation": "Changed-user-pass-12345!",
            },
        )
        assert changed.status_code == 200
        assert newcomer.get("/api/auth/me").status_code == 401
        assert login(newcomer, "new.user", "Changed-user-pass-12345!").status_code == 200
        assert newcomer.get("/").status_code == 200
        assert newcomer.get("/admin/users").status_code == 403


@pytest.mark.parametrize("path", ["/api/admin/users", "/api/admin/organizations"])
def test_permissions_and_csrf(client, admin, db_session, path):
    payload = new_user(admin.organization_id) if path.endswith("users") else {"name": "신규 조직"}
    assert client.post(path, json=payload, headers=ORIGIN).status_code == 403
    assert (
        client.post(
            path,
            json=payload,
            headers={"Origin": "https://foreign.test", "X-CSRF-Token": token(client)},
        ).status_code
        == 403
    )
    admin.system_role = "USER"
    db_session.commit()
    assert client.get(path).status_code == 403
    assert post(client, path, payload).status_code == 403
    admin.system_role = "SYSTEM_ADMIN"
    admin.must_change_password = True
    db_session.commit()
    assert client.get(path).status_code == 403
    assert post(client, path, payload).status_code == 403
    admin.is_active = False
    db_session.commit()
    assert client.get(path).status_code == 401
    assert post(client, path, payload).status_code == 401
    with TestClient(app) as anonymous:
        assert anonymous.get(path).status_code == 401
        assert post(anonymous, path, payload).status_code == 401


@pytest.mark.parametrize("path", ["/admin/users", "/admin/organizations"])
def test_web_writes_require_admin_and_csrf(client, admin, db_session, path):
    assert client.post(path, data={}, headers=ORIGIN).status_code == 403
    admin.system_role = "USER"
    db_session.commit()
    assert client.get(path).status_code == 403
    assert client.post(path, data={}).status_code == 403
    with TestClient(app) as anonymous:
        assert anonymous.post(path, data={}, follow_redirects=False).status_code == 303


def test_duplicate_names_ids_emails_and_rollback(client, admin, db_session):
    assert post(client, "/api/admin/organizations", {"name": " 기본 조직 "}).status_code == 409
    assert (
        post(
            client,
            "/api/admin/organizations",
            {"name": "개발팀", "parent_id": admin.organization_id},
        ).status_code
        == 201
    )
    assert (
        post(
            client,
            "/api/admin/organizations",
            {"name": "개발팀", "parent_id": admin.organization_id},
        ).status_code
        == 409
    )
    assert post(client, "/api/admin/organizations", {"name": "개발팀"}).status_code == 201
    assert (
        post(
            client, "/api/admin/users", new_user(admin.organization_id, email="New@Example.com")
        ).status_code
        == 201
    )
    assert post(client, "/api/admin/users", new_user(admin.organization_id)).status_code == 409
    assert (
        post(
            client,
            "/api/admin/users",
            new_user(admin.organization_id, login_id="another", email="new@example.com"),
        ).status_code
        == 409
    )
    assert db_session.scalar(select(func.count()).select_from(User)) == 2
    assert (
        db_session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "user.created")
        )
        == 1
    )


def test_inactive_ancestors_and_missing_organizations(client, admin, db_session):
    parent = Organization(key="inactive", name="비활성 본부", is_active=False)
    db_session.add(parent)
    db_session.flush()
    child = Organization(key="child", name="활성 팀", parent_id=parent.id)
    db_session.add(child)
    db_session.commit()
    for org_id in [parent.id, child.id, 99999]:
        assert post(client, "/api/admin/users", new_user(org_id)).status_code == 400
        assert (
            post(
                client, "/api/admin/organizations", {"name": "신규 조직", "parent_id": org_id}
            ).status_code
            == 400
        )
    rows = client.get("/api/admin/organizations").json()
    assert not next(row for row in rows if row["id"] == child.id)["selectable"]
    assert db_session.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"display_name": " "},
        {"login_id": "invalid@login"},
        {"password": "short"},
        {"password": " " * 12},
        {"system_role": "ROOT"},
        {"email": "not-an-email"},
        {"organization_id": 0},
        {"unexpected": True},
    ],
)
def test_invalid_user_inputs_leave_no_data(client, admin, db_session, overrides):
    response = post(client, "/api/admin/users", new_user(admin.organization_id, **overrides))
    assert response.status_code in {400, 422}
    assert db_session.scalar(select(func.count()).select_from(User)) == 1


def test_form_preserves_safe_values_but_never_password(client, admin, db_session):
    values = new_user(admin.organization_id, display_name='<script>alert("x")</script>')
    values.update(csrf_token=token(client), password="ShortSecret")
    response = client.post("/admin/users", data=values, headers=ORIGIN)
    assert response.status_code == 400
    assert "ShortSecret" not in response.text
    assert '<script>alert("x")</script>' not in response.text
    assert "&lt;script&gt;" in response.text
    values.update(password="New-user-pass-12345!")
    created = client.post("/admin/users", data=values, headers=ORIGIN, follow_redirects=False)
    assert created.status_code == 303
    page = client.get(created.headers["location"])
    assert "&lt;script&gt;" in page.text and "New-user-pass-12345!" not in page.text
    assert 'value="New-user' not in page.text


def test_organization_form_and_empty_validation(client, admin):
    page = client.get("/admin/organizations")
    csrf = re.search('name="csrf_token" value="([^"]+)"', page.text).group(1)
    response = client.post(
        "/admin/organizations",
        data={"name": "새 본부", "parent_id": "", "csrf_token": csrf},
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "새 본부" in client.get(response.headers["location"]).text
    invalid = client.post(
        "/admin/organizations", data={"name": " ", "csrf_token": csrf}, headers=ORIGIN
    )
    assert invalid.status_code == 422 and "조직명" in invalid.text


def test_search_pagination_and_public_fields(client, admin, db_session):
    for index in range(23):
        db_session.add(
            User(
                login_id=f"member{index:02}",
                display_name=f"검색 대상 {index}",
                organization_id=admin.organization_id,
                password_hash=admin.password_hash,
            )
        )
    db_session.commit()
    first = client.get("/api/admin/users?q=검색&page_size=10").json()
    second = client.get("/api/admin/users?q=검색&page_size=10&page=2").json()
    assert first["total"] == second["total"] == 23
    assert len(first["users"]) == len(second["users"]) == 10
    assert not ({row["id"] for row in first["users"]} & {row["id"] for row in second["users"]})
    assert "password_hash" not in str(first) and "sessions" not in str(first)
    assert client.get("/api/admin/users?q=%25").json()["total"] == 0
    assert client.get("/api/admin/users?page=0").status_code == 400
    assert client.get("/api/admin/users?page_size=1000").status_code == 400
    page = client.get("/admin/users?q=검색&page_size=10").text
    assert "page=2" in page and "q=%EA%B2%80%EC%83%89" in page


def test_creation_audit_failure_rolls_back(client, admin, db_session_factory, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(service, "record_audit_event", fail)
    with db_session_factory() as session:
        identity = get_current_identity(
            session, client.cookies.get(get_settings().session.cookie_name)
        )
        with pytest.raises(RuntimeError, match="audit failure"):
            service.create_organization(
                session, identity, OrganizationCreate(name="롤백 조직"), "127.0.0.1"
            )
        assert session.scalar(select(Organization).where(Organization.name == "롤백 조직")) is None


def test_concurrent_organization_creation_is_unique(client, admin, db_session_factory):
    raw_token = client.cookies.get(get_settings().session.cookie_name)

    def create(_):
        from app.domain.auth import AuthError

        with db_session_factory() as session:
            identity = get_current_identity(session, raw_token)
            try:
                service.create_organization(
                    session, identity, OrganizationCreate(name="동시 생성"), "127.0.0.1"
                )
                return 201
            except AuthError as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create, range(2))) == [201, 409]
