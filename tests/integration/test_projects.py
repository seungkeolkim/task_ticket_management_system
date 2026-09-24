from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.domain.auth import AuthError, hash_password
from app.models import AuditLog, Organization, Project, ProjectMember, User
from app.schemas.projects import MemberCreate, ProjectCreate
from app.services import projects as service
from app.services.auth import get_current_identity

PASSWORD = "Project-test-password-123!"
ORIGIN = {"Origin": "http://testserver"}


def token(client):
    return client.get("/api/auth/csrf").json()["csrf_token"]


def post(client, path, payload):
    return client.post(path, json=payload, headers=ORIGIN | {"X-CSRF-Token": token(client)})


def login(client, login_id):
    client.cookies.clear()
    assert (
        post(client, "/api/auth/login", {"login_id": login_id, "password": PASSWORD}).status_code
        == 200
    )


@pytest.fixture
def people(client, db_session):
    org = Organization(key="project-test", name="같은 조직")
    db_session.add(org)
    db_session.flush()
    accounts = {}
    password_hash = hash_password(PASSWORD)
    for name in ["sysadmin", "manager", "member", "outsider"]:
        user = User(
            login_id=name,
            display_name=name,
            organization_id=org.id,
            password_hash=password_hash,
            must_change_password=False,
            system_role="SYSTEM_ADMIN" if name == "sysadmin" else "USER",
        )
        db_session.add(user)
        accounts[name] = user
    db_session.commit()
    login(client, "sysadmin")
    return accounts


def create(client, people, key="DEV", **overrides):
    return post(
        client,
        "/api/admin/projects",
        dict(
            key=key,
            name="실제 개발 프로젝트",
            description="프로젝트 설명",
            administrator_id=people["manager"].id,
        )
        | overrides,
    )


def test_create_register_and_my_projects_flow(client, people, db_session):
    created = create(client, people, " dev ")
    assert created.status_code == 201
    assert created.json()["key"] == "DEV"
    assert client.get("/api/projects").json()["total"] == 0
    assert client.get("/api/admin/projects").json()["total"] == 1
    login(client, "manager")
    mine = client.get("/api/projects").json()
    assert mine["total"] == 1 and mine["projects"][0]["role"] == "PROJECT_ADMIN"
    assert "실제 개발 프로젝트" in client.get("/projects").text
    assert (
        post(
            client,
            "/api/projects/DEV/members",
            {"user_id": people["member"].id, "role": "PROJECT_USER"},
        ).status_code
        == 201
    )
    assert (
        post(
            client,
            "/api/projects/DEV/members",
            {"user_id": people["outsider"].id, "role": "PROJECT_GUEST"},
        ).status_code
        == 201
    )
    login(client, "outsider")
    guest_projects = client.get("/api/projects").json()
    assert guest_projects["projects"][0]["role"] == "PROJECT_GUEST"
    assert "게스트" in client.get("/projects").text
    assert "프로젝트 게스트" in client.get("/projects/DEV/members").text
    login(client, "member")
    assert client.get("/api/projects").json()["total"] == 1
    page = client.get("/projects/DEV/members")
    assert page.status_code == 200 and "manager" in page.text
    assert 'name="user_id"' not in page.text
    assert client.get("/api/projects/DEV/candidates").status_code == 403
    assert (
        post(client, "/api/projects/DEV/members", {"user_id": people["outsider"].id}).status_code
        == 403
    )
    events = list(
        db_session.scalars(select(AuditLog).where(AuditLog.action == "project.member_added"))
    )
    assert len(events) == 3
    assert events[-1].details == {"user_id": people["outsider"].id, "role": "PROJECT_GUEST"}


@pytest.mark.parametrize(
    "suffix",
    [
        "",
        "/settings",
        "/members",
        "/tickets",
        "/tickets/new",
        "/tickets/DEV-1",
        "/tickets/DEV-1/edit",
        "/board",
        "/trash",
    ],
)
def test_project_paths_hide_existence_from_same_organization(client, people, suffix):
    assert create(client, people).status_code == 201
    login(client, "outsider")
    assert client.get("/api/projects").json()["total"] == 0
    hidden = client.get("/projects/DEV" + suffix)
    missing = client.get("/projects/MISSING" + suffix)
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()
    assert "실제 개발 프로젝트" not in client.get("/projects").text
    assert client.get("/api/projects/DEV").status_code == 404
    assert client.get("/api/projects/DEV/members").status_code == 404
    assert client.get("/api/projects/DEV/candidates").status_code == 404
    assert (
        post(client, "/api/projects/DEV/members", {"user_id": people["outsider"].id}).status_code
        == 404
    )


def test_permissions_csrf_and_inactive_accounts(client, people, db_session):
    assert create(client, people).status_code == 201
    path = "/api/projects/DEV/members"
    payload = {"user_id": people["member"].id}
    assert client.post(path, json=payload, headers=ORIGIN).status_code == 403
    assert (
        client.post(
            path,
            json=payload,
            headers={"Origin": "https://evil.test", "X-CSRF-Token": token(client)},
        ).status_code
        == 403
    )
    assert client.post("/admin/projects", data={}).status_code == 403
    assert client.post("/projects/DEV/members", data={}).status_code == 403
    login(client, "manager")
    assert create(client, people, "OTHER").status_code == 403
    assert client.get("/api/admin/projects").status_code == 403
    assert client.get("/api/admin/project-candidates").status_code == 403
    people["manager"].must_change_password = True
    db_session.commit()
    assert client.get("/api/projects").status_code == 403
    people["manager"].is_active = False
    db_session.commit()
    assert client.get("/api/projects").status_code == 401
    client.cookies.clear()
    assert client.get("/api/projects/DEV").status_code == 401
    assert client.get("/projects/DEV", follow_redirects=False).status_code == 303


@pytest.mark.parametrize(
    "overrides",
    [
        {"key": "A"},
        {"key": "BAD-KEY"},
        {"key": "1BAD"},
        {"key": "한글"},
        {"name": " "},
        {"administrator_id": 99999},
        {"unexpected": True},
    ],
)
def test_invalid_creation_is_atomic(client, people, db_session, overrides):
    assert create(client, people, **overrides).status_code in {400, 422}
    assert db_session.scalar(select(func.count()).select_from(Project)) == 0
    assert db_session.scalar(select(func.count()).select_from(ProjectMember)) == 0


def test_duplicates_inactive_users_and_projects(client, people, db_session):
    assert create(client, people).status_code == 201
    assert create(client, people, "dev").status_code == 409
    assert (
        post(client, "/api/projects/DEV/members", {"user_id": people["manager"].id}).status_code
        == 409
    )
    people["member"].is_active = False
    db_session.commit()
    assert create(client, people, "NEW", administrator_id=people["member"].id).status_code == 400
    assert (
        post(client, "/api/projects/DEV/members", {"user_id": people["member"].id}).status_code
        == 400
    )
    assert post(client, "/api/projects/DEV/members", {"user_id": 99999}).status_code == 400
    assert (
        post(
            client,
            "/api/projects/DEV/members",
            {"user_id": people["outsider"].id, "role": "SYSTEM_ADMIN"},
        ).status_code
        == 422
    )
    project = db_session.scalar(select(Project))
    project.is_active = False
    db_session.commit()
    assert (
        post(client, "/api/projects/DEV/members", {"user_id": people["outsider"].id}).status_code
        == 409
    )
    assert client.get("/api/projects/DEV").json()["project"]["is_active"] is False


def test_override_audits_and_member_role_do_not_leak_privileges(client, people, db_session):
    create(client, people)
    before = db_session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "project.override_access")
    )
    assert client.get("/api/projects/DEV").status_code == 200
    event = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "project.override_access")
    ).all()
    assert len(event) == before + 1 and event[-1].details["permission"] == "read"
    assert (
        post(client, "/api/projects/DEV/members", {"user_id": people["sysadmin"].id}).status_code
        == 201
    )
    count = len(
        db_session.scalars(
            select(AuditLog).where(AuditLog.action == "project.override_access")
        ).all()
    )
    assert client.get("/api/projects/DEV/candidates").status_code == 200
    assert (
        len(
            db_session.scalars(
                select(AuditLog).where(AuditLog.action == "project.override_access")
            ).all()
        )
        == count + 1
    )


def test_html_forms_escape_input_and_refresh_from_database(client, people):
    values = dict(
        key="WEB",
        name='<script>alert("x")</script>',
        description="화면 생성",
        administrator_id=str(people["manager"].id),
        csrf_token=token(client),
    )
    response = client.post("/admin/projects", data=values, headers=ORIGIN, follow_redirects=False)
    assert response.status_code == 303
    page = client.get(response.headers["location"])
    assert "프로젝트를 생성" in page.text and "&lt;script&gt;" in page.text
    assert '<script>alert("x")</script>' not in page.text
    invalid = client.post("/admin/projects", data=values | {"key": "?"}, headers=ORIGIN)
    assert invalid.status_code == 422 and "&lt;script&gt;" in invalid.text
    login(client, "manager")
    response = client.post(
        "/projects/WEB/members",
        data={"csrf_token": token(client), "user_id": people["member"].id, "role": "PROJECT_ADMIN"},
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "member" in client.get(response.headers["location"]).text
    login(client, "member")
    assert client.get("/api/projects/WEB").json()["project"]["can_manage"]


def test_filters_pagination_and_candidate_data(client, people, db_session):
    for i in range(23):
        project = Project(
            key=f"PR{i}", name=f"검색 프로젝트 {i:02}", created_by_id=people["sysadmin"].id
        )
        db_session.add(project)
        db_session.flush()
        db_session.add(ProjectMember(project_id=project.id, user_id=people["manager"].id))
    db_session.commit()
    candidates = client.get("/api/admin/project-candidates?q=manager").json()
    assert len(candidates) == 1 and set(candidates[0]) == {"id", "login_id", "display_name"}
    login(client, "manager")
    first = client.get("/api/projects?q=검색&page_size=10").json()
    second = client.get("/api/projects?q=검색&page_size=10&page=2").json()
    assert first["total"] == second["total"] == 23
    assert len(first["projects"]) == len(second["projects"]) == 10
    assert not ({p["id"] for p in first["projects"]} & {p["id"] for p in second["projects"]})
    assert client.get("/api/projects?q=%25").json()["total"] == 0
    assert client.get("/api/projects?page_size=100").status_code == 400
    assert client.get("/api/projects?page=0").status_code == 400
    assert "page=2" in client.get("/projects?q=검색&page_size=10").text


def test_audit_failures_rollback_create_add_and_override(
    client, people, db_session_factory, monkeypatch
):
    create(client, people)
    raw_token = client.cookies.get(get_settings().session.cookie_name)

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(service, "record_project_audit_event", fail)
    with db_session_factory() as session:
        actor = get_current_identity(session, raw_token)
        with pytest.raises(RuntimeError):
            service.create_project(
                session,
                actor,
                ProjectCreate(key="ROLLBACK", name="롤백", administrator_id=people["manager"].id),
            )
        assert session.scalar(select(Project).where(Project.key == "ROLLBACK")) is None
        with pytest.raises(RuntimeError):
            service.get_project_detail(session, actor, "DEV")
    login(client, "manager")
    with db_session_factory() as session:
        actor = get_current_identity(
            session, client.cookies.get(get_settings().session.cookie_name)
        )
        with pytest.raises(RuntimeError):
            service.add_project_member(
                session, actor, "DEV", MemberCreate(user_id=people["member"].id)
            )
        assert (
            session.scalar(
                select(ProjectMember).where(ProjectMember.user_id == people["member"].id)
            )
            is None
        )


def test_concurrent_project_and_membership_creation(client, people, db_session_factory):
    raw_token = client.cookies.get(get_settings().session.cookie_name)

    def attempt(member):
        with db_session_factory() as session:
            actor = get_current_identity(session, raw_token)
            try:
                if member:
                    service.add_project_member(
                        session, actor, "RACE", MemberCreate(user_id=people["member"].id)
                    )
                else:
                    service.create_project(
                        session,
                        actor,
                        ProjectCreate(
                            key="RACE", name="동시 생성", administrator_id=people["manager"].id
                        ),
                    )
                return 201
            except AuthError as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, [False, False])) == [201, 409]
        assert sorted(pool.map(attempt, [True, True])) == [201, 409]


def test_repository_member_scope_and_cross_organization_membership(client, people, db_session):
    from app.repositories import projects as repository

    create(client, people)
    project = db_session.scalar(select(Project))
    assert repository.list_project_members(db_session, project.id, people["outsider"].id) == []
    other = Organization(key="another", name="다른 조직")
    db_session.add(other)
    db_session.flush()
    people["member"].organization_id = other.id
    db_session.commit()
    login(client, "manager")
    assert (
        post(client, "/api/projects/DEV/members", {"user_id": people["member"].id}).status_code
        == 201
    )
    login(client, "member")
    assert client.get("/api/projects").json()["total"] == 1
    people["member"].organization_id = people["manager"].organization_id
    db_session.commit()
    assert client.get("/api/projects/DEV").status_code == 200


def test_stale_identity_does_not_allow_project_writes(client, people, db_session_factory):
    create(client, people)
    raw_token = client.cookies.get(get_settings().session.cookie_name)
    with db_session_factory() as session:
        actor = get_current_identity(session, raw_token)
        with db_session_factory() as changed:
            user = changed.get(User, people["sysadmin"].id)
            user.system_role = "USER"
            changed.commit()
        with pytest.raises(AuthError) as error:
            service.create_project(
                session,
                actor,
                ProjectCreate(key="DENIED", name="거부", administrator_id=people["manager"].id),
            )
        assert error.value.status_code == 403
    login(client, "manager")
    with db_session_factory() as session:
        actor = get_current_identity(
            session, client.cookies.get(get_settings().session.cookie_name)
        )
        with db_session_factory() as changed:
            membership = changed.scalar(
                select(ProjectMember).where(ProjectMember.user_id == people["manager"].id)
            )
            membership.role = "PROJECT_USER"
            changed.commit()
        with pytest.raises(AuthError) as error:
            service.add_project_member(
                session, actor, "DEV", MemberCreate(user_id=people["member"].id)
            )
        assert error.value.status_code == 403
