from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.domain.auth import AuthError, hash_password
from app.models import AuditLog, Organization, Project, ProjectMember, Ticket, User
from app.schemas.projects import MemberCreate, MemberRoleUpdate, ProjectCreate, ProjectUpdate
from app.services import projects as service
from app.services.auth import get_current_identity

PASSWORD = "Project-test-password-123!"
ORIGIN = {"Origin": "http://testserver"}


def token(client):
    """테스트 client의 CSRF token을 반환한다."""
    return client.get("/api/auth/csrf").json()["csrf_token"]


def post(client, path, payload):
    """CSRF 보호가 적용된 테스트 POST 요청을 보낸다."""
    return client.post(path, json=payload, headers=ORIGIN | {"X-CSRF-Token": token(client)})


def patch(client, path, payload):
    """CSRF 보호가 적용된 테스트 PATCH 요청을 보낸다."""
    return client.patch(path, json=payload, headers=ORIGIN | {"X-CSRF-Token": token(client)})


def delete(client, path):
    """CSRF 보호가 적용된 테스트 DELETE 요청을 보낸다."""
    return client.delete(path, headers=ORIGIN | {"X-CSRF-Token": token(client)})


def login(client, login_id):
    """사용자 인증 후 session 정보를 반환한다."""
    client.cookies.clear()
    assert (
        post(client, "/api/auth/login", {"login_id": login_id, "password": PASSWORD}).status_code
        == 200
    )


@pytest.fixture
def people(client, db_session):
    """프로젝트 테스트용 사용자 집합을 생성한다."""
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
    """동시성 테스트용 생성 시도를 수행한다."""
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
    """프로젝트 관련 동작을 검증한다."""
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
    """조직·프로젝트 관련 동작을 검증한다."""
    assert create(client, people).status_code == 201
    login(client, "outsider")
    assert client.get("/api/projects").json()["total"] == 0
    hidden = client.get("/projects/DEV" + suffix)
    missing = client.get("/projects/MISSING" + suffix)
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()
    assert "실제 개발 프로젝트" not in client.get("/projects").text
    assert client.get("/api/projects/DEV").status_code == 404
    assert patch(client, "/api/projects/DEV", {"name": "숨은 프로젝트"}).status_code == 404
    assert client.get("/api/projects/DEV/members").status_code == 404
    assert client.get("/api/projects/DEV/candidates").status_code == 404
    assert (
        post(client, "/api/projects/DEV/members", {"user_id": people["outsider"].id}).status_code
        == 404
    )
    assert (
        patch(client, "/api/projects/DEV/members/1", {"role": "PROJECT_USER"}).status_code
        == 404
    )
    assert delete(client, "/api/projects/DEV/members/1").status_code == 404


def test_permissions_csrf_and_inactive_accounts(client, people, db_session):
    """CSRF·권한 관련 동작을 검증한다."""
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
    assert client.patch(
        "/api/projects/DEV", json={"name": "변경"}, headers=ORIGIN
    ).status_code == 403
    assert client.post("/projects/DEV/settings", data={}).status_code == 403
    assert client.post("/projects/DEV/members", data={}).status_code == 403
    manager_member_id = db_session.scalar(
        select(ProjectMember.id).where(ProjectMember.user_id == people["manager"].id)
    )
    db_session.rollback()
    assert (
        client.patch(
            f"/api/projects/DEV/members/{manager_member_id}",
            json={"role": "PROJECT_ADMIN"},
            headers=ORIGIN,
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/projects/DEV/members/{manager_member_id}", headers=ORIGIN
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/projects/DEV/members/{manager_member_id}/role", data={}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/projects/DEV/members/{manager_member_id}/remove", data={}
        ).status_code
        == 403
    )
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
    """잘못된 프로젝트 생성 요청의 원자성을 검증한다."""
    assert create(client, people, **overrides).status_code in {400, 422}
    assert db_session.scalar(select(func.count()).select_from(Project)) == 0
    assert db_session.scalar(select(func.count()).select_from(ProjectMember)) == 0


def test_duplicates_inactive_users_and_projects(client, people, db_session):
    """프로젝트·사용자 관련 동작을 검증한다."""
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
    """감사 로그 관련 동작을 검증한다."""
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


def test_project_update_deactivate_reactivate_and_noop(client, people, db_session):
    """프로젝트 수정·비활성화·재활성화와 no-op을 검증한다."""
    assert create(client, people).status_code == 201
    login(client, "manager")
    updated = patch(
        client,
        "/api/projects/DEV",
        {"name": "  변경된 프로젝트  ", "description": "  변경된 설명  "},
    )
    assert updated.status_code == 200
    assert updated.json() == {
        "id": updated.json()["id"],
        "key": "DEV",
        "name": "변경된 프로젝트",
        "description": "변경된 설명",
        "is_active": True,
        "role": "PROJECT_ADMIN",
        "can_manage": True,
    }
    project = db_session.scalar(select(Project).where(Project.key == "DEV"))
    before_noop_updated_at = project.updated_at
    update_audit_count = db_session.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "project.updated")
    )
    db_session.rollback()
    assert patch(client, "/api/projects/DEV", {"name": "변경된 프로젝트"}).status_code == 200
    project = db_session.scalar(select(Project).where(Project.key == "DEV"))
    assert project.updated_at == before_noop_updated_at
    assert (
        db_session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "project.updated")
        )
        == update_audit_count
    )
    db_session.rollback()

    assert (
        post(client, "/api/projects/DEV/members", {"user_id": people["member"].id}).status_code
        == 201
    )
    deactivated = patch(client, "/api/projects/DEV", {"is_active": False})
    assert deactivated.status_code == 200 and deactivated.json()["is_active"] is False
    assert client.get("/api/projects/DEV").status_code == 200
    assert (
        post(client, "/api/projects/DEV/members", {"user_id": people["outsider"].id}).json()[
            "code"
        ]
        == "project_inactive"
    )
    blocked_ticket = post(
        client,
        "/api/projects/DEV/tickets",
        {"type": "TASK", "title": "비활성 프로젝트 티켓", "priority": "MAJOR"},
    )
    assert blocked_ticket.status_code == 409
    assert blocked_ticket.json()["code"] == "project_inactive"
    reactivated = patch(client, "/api/projects/DEV", {"is_active": True})
    assert reactivated.status_code == 200 and reactivated.json()["is_active"] is True
    assert (
        post(client, "/api/projects/DEV/members", {"user_id": people["outsider"].id}).status_code
        == 201
    )
    status_events = list(
        db_session.scalars(
            select(AuditLog).where(
                AuditLog.action.in_(("project.deactivated", "project.reactivated"))
            ).order_by(AuditLog.id)
        )
    )
    assert [event.action for event in status_events] == [
        "project.deactivated",
        "project.reactivated",
    ]
    assert status_events[0].details == {
        "before_is_active": True,
        "after_is_active": False,
    }
    assert status_events[1].details == {
        "before_is_active": False,
        "after_is_active": True,
    }


def test_project_update_permissions_validation_and_override_audit(
    client, people, db_session
):
    """프로젝트 수정 권한·입력 검증과 시스템 관리자 override를 검증한다."""
    assert create(client, people).status_code == 201
    assert patch(client, "/api/projects/DEV", {}).status_code == 422
    assert patch(client, "/api/projects/DEV", {"name": None}).status_code == 422
    assert patch(client, "/api/projects/DEV", {"name": " "}).status_code == 422
    assert patch(client, "/api/projects/DEV", {"key": "CHANGED"}).status_code == 422

    override_count = db_session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "project.override_access")
    )
    changed = patch(client, "/api/projects/DEV", {"description": "시스템 관리자 변경"})
    assert changed.status_code == 200
    assert changed.json()["role"] is None and changed.json()["can_manage"] is True
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "project.override_access")
        )
        == override_count + 1
    )
    project_update_count = db_session.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "project.updated")
    )
    override_count_after_change = db_session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "project.override_access")
    )
    db_session.rollback()
    assert (
        patch(client, "/api/projects/DEV", {"description": "시스템 관리자 변경"}).status_code
        == 200
    )
    assert (
        db_session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "project.updated")
        )
        == project_update_count
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "project.override_access")
        )
        == override_count_after_change + 1
    )
    db_session.rollback()

    login(client, "manager")
    assert (
        post(client, "/api/projects/DEV/members", {"user_id": people["member"].id}).status_code
        == 201
    )
    login(client, "member")
    assert patch(client, "/api/projects/DEV", {"name": "권한 없음"}).status_code == 403
    assert 'action="/projects/DEV/settings"' not in client.get("/projects/DEV/settings").text
    login(client, "outsider")
    assert patch(client, "/api/projects/DEV", {"name": "숨은 변경"}).status_code == 404


def test_html_forms_escape_input_and_refresh_from_database(client, people):
    """DB·HTML 관련 동작을 검증한다."""
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
    settings_page = client.get("/projects/WEB/settings")
    assert settings_page.status_code == 200
    assert 'action="/projects/WEB/settings"' in settings_page.text
    settings_response = client.post(
        "/projects/WEB/settings",
        data={
            "csrf_token": token(client),
            "name": '<script>alert("project")</script>',
            "description": "화면 변경",
            "is_active": "false",
        },
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert settings_response.status_code == 303
    updated_settings_page = client.get(settings_response.headers["location"])
    assert "프로젝트 정보를 저장" in updated_settings_page.text
    assert "&lt;script&gt;" in updated_settings_page.text
    assert '<script>alert("project")</script>' not in updated_settings_page.text
    assert "비활성" in updated_settings_page.text
    reactivated_response = client.post(
        "/projects/WEB/settings",
        data={
            "csrf_token": token(client),
            "name": "화면 프로젝트",
            "description": "화면 변경",
            "is_active": "true",
        },
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert reactivated_response.status_code == 303
    response = client.post(
        "/projects/WEB/members",
        data={"csrf_token": token(client), "user_id": people["member"].id, "role": "PROJECT_ADMIN"},
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "member" in client.get(response.headers["location"]).text
    member_id = next(
        member["id"]
        for member in client.get("/api/projects/WEB/members").json()
        if member["user_id"] == people["member"].id
    )
    missing = client.post(
        "/projects/WEB/members/999999/remove",
        data={"csrf_token": token(client)},
        headers=ORIGIN,
    )
    assert missing.status_code == 404
    assert "프로젝트 참여자를 찾을 수 없습니다" in missing.text and "manager" in missing.text
    changed = client.post(
        f"/projects/WEB/members/{member_id}/role",
        data={"csrf_token": token(client), "role": "PROJECT_USER"},
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert changed.status_code == 303
    assert "참여자 역할을 변경" in client.get(changed.headers["location"]).text
    removed = client.post(
        f"/projects/WEB/members/{member_id}/remove",
        data={"csrf_token": token(client)},
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert removed.status_code == 303
    assert "프로젝트 참여자를 제거" in client.get(removed.headers["location"]).text
    assert (
        post(
            client,
            "/api/projects/WEB/members",
            {"user_id": people["member"].id, "role": "PROJECT_ADMIN"},
        ).status_code
        == 201
    )
    login(client, "member")
    assert client.get("/api/projects/WEB").json()["project"]["can_manage"]


def test_filters_pagination_and_candidate_data(client, people, db_session):
    """필터 관련 동작을 검증한다."""
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
    """감사 로그 관련 동작을 검증한다."""
    create(client, people)
    assert (
        post(client, "/api/projects/DEV/members", {"user_id": people["member"].id}).status_code
        == 201
    )
    raw_token = client.cookies.get(get_settings().session.cookie_name)

    def fail(*args, **kwargs):
        """실패 rollback 상황을 재현한다."""
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
            service.update_project(
                session,
                actor,
                "DEV",
                ProjectUpdate(name="감사 실패"),
            )
        project = session.scalar(select(Project).where(Project.key == "DEV"))
        assert project.name == "실제 개발 프로젝트"
        with pytest.raises(RuntimeError):
            service.add_project_member(
                session, actor, "DEV", MemberCreate(user_id=people["outsider"].id)
            )
        assert (
            session.scalar(
                select(ProjectMember).where(ProjectMember.user_id == people["outsider"].id)
            )
            is None
        )
        member = session.scalar(
            select(ProjectMember).where(ProjectMember.user_id == people["member"].id)
        )
        with pytest.raises(RuntimeError):
            service.update_project_member_role(
                session,
                actor,
                "DEV",
                member.id,
                MemberRoleUpdate(role="PROJECT_GUEST"),
            )
        assert session.get(ProjectMember, member.id).role == "PROJECT_USER"
        with pytest.raises(RuntimeError):
            service.remove_project_member(session, actor, "DEV", member.id)
        assert session.get(ProjectMember, member.id) is not None


def test_concurrent_project_and_membership_creation(client, people, db_session_factory):
    """프로젝트·동시성 관련 동작을 검증한다."""
    raw_token = client.cookies.get(get_settings().session.cookie_name)

    def attempt(member):
        """동시성 테스트용 작업 시도를 수행한다."""
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
    """조직 관련 동작을 검증한다."""
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
    """프로젝트 관련 동작을 검증한다."""
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


def test_member_role_update_remove_and_last_administrator_guard(
    client, people, db_session
):
    """참여자 역할 변경·제거와 마지막 관리자 보호를 검증한다."""
    assert create(client, people).status_code == 201
    login(client, "manager")
    assert (
        post(
            client,
            "/api/projects/DEV/members",
            {"user_id": people["member"].id, "role": "PROJECT_USER"},
        ).status_code
        == 201
    )
    memberships = {
        item["user_id"]: item for item in client.get("/api/projects/DEV/members").json()
    }
    member_path = f"/api/projects/DEV/members/{memberships[people['member'].id]['id']}"
    promoted = patch(client, member_path, {"role": "PROJECT_ADMIN"})
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "PROJECT_ADMIN"

    manager_path = f"/api/projects/DEV/members/{memberships[people['manager'].id]['id']}"
    assert patch(client, manager_path, {"role": "PROJECT_USER"}).status_code == 200
    assert patch(client, member_path, {"role": "PROJECT_ADMIN"}).status_code == 403
    login(client, "member")
    assert patch(client, member_path, {"role": "PROJECT_GUEST"}).status_code == 409
    assert delete(client, member_path).status_code == 409

    assert patch(client, manager_path, {"role": "PROJECT_ADMIN"}).status_code == 200
    assert patch(client, member_path, {"role": "PROJECT_USER"}).status_code == 200
    login(client, "manager")
    assert delete(client, member_path).status_code == 204
    login(client, "member")
    assert client.get("/api/projects/DEV").status_code == 404

    actions = list(
        db_session.scalars(
            select(AuditLog.action).where(
                AuditLog.action.in_(
                    ("project.member_role_changed", "project.member_removed")
                )
            )
        )
    )
    assert actions.count("project.member_role_changed") == 4
    assert actions.count("project.member_removed") == 1


def test_member_noop_override_audit_and_inactive_role_expansion(
    client, people, db_session
):
    """no-op override 감사와 비활성 상태의 권한 확대 차단을 검증한다."""
    manager_user_id = people["manager"].id
    member_user_id = people["member"].id
    assert create(client, people).status_code == 201
    manager_membership = db_session.scalar(
        select(ProjectMember).where(ProjectMember.user_id == manager_user_id)
    )
    role_audit_count = db_session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "project.member_role_changed")
    )
    override_audit_count = db_session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "project.override_access")
    )
    manager_membership_id = manager_membership.id
    db_session.rollback()
    noop = patch(
        client,
        f"/api/projects/DEV/members/{manager_membership_id}",
        {"role": "PROJECT_ADMIN"},
    )
    assert noop.status_code == 200
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "project.member_role_changed")
        )
        == role_audit_count
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "project.override_access")
        )
        == override_audit_count + 1
    )
    db_session.rollback()

    login(client, "manager")
    assert (
        post(client, "/api/projects/DEV/members", {"user_id": member_user_id}).status_code
        == 201
    )
    member = db_session.scalar(
        select(ProjectMember).where(ProjectMember.user_id == member_user_id)
    )
    people["member"].is_active = False
    db_session.commit()
    assert (
        patch(
            client,
            f"/api/projects/DEV/members/{member.id}",
            {"role": "PROJECT_ADMIN"},
        ).json()["code"]
        == "inactive_member_role_expansion"
    )
    assert (
        patch(
            client,
            f"/api/projects/DEV/members/{member.id}",
            {"role": "PROJECT_GUEST"},
        ).status_code
        == 200
    )
    project = db_session.scalar(select(Project).where(Project.key == "DEV"))
    project.is_active = False
    people["member"].is_active = True
    db_session.commit()
    assert (
        patch(
            client,
            f"/api/projects/DEV/members/{member.id}",
            {"role": "PROJECT_USER"},
        ).json()["code"]
        == "project_inactive_role_expansion"
    )
    assert delete(client, f"/api/projects/DEV/members/{member.id}").status_code == 204


def test_member_with_active_assignment_cannot_be_guest_or_removed(
    client, people, db_session
):
    """미완료 담당 티켓이 있는 참여자의 게스트 하향·제거를 차단한다."""
    assert create(client, people).status_code == 201
    login(client, "manager")
    assert (
        post(client, "/api/projects/DEV/members", {"user_id": people["member"].id}).status_code
        == 201
    )
    project = db_session.scalar(select(Project).where(Project.key == "DEV"))
    member = db_session.scalar(
        select(ProjectMember).where(ProjectMember.user_id == people["member"].id)
    )
    db_session.add(
        Ticket(
            project_id=project.id,
            number=1,
            key="DEV-1",
            type="TASK",
            title="담당 중인 티켓",
            creator_id=people["manager"].id,
            assignee_id=people["member"].id,
        )
    )
    db_session.commit()
    path = f"/api/projects/DEV/members/{member.id}"
    demoted = patch(client, path, {"role": "PROJECT_GUEST"})
    removed = delete(client, path)
    assert demoted.status_code == removed.status_code == 409
    assert demoted.json()["code"] == removed.json()["code"] == "member_has_active_assignments"


def test_concurrent_administrator_demotions_keep_one_administrator(
    client, people, db_session, db_session_factory
):
    """동시 관리자 하향에서도 최소 한 명의 관리자를 유지한다."""
    assert create(client, people).status_code == 201
    assert (
        post(
            client,
            "/api/projects/DEV/members",
            {"user_id": people["member"].id, "role": "PROJECT_ADMIN"},
        ).status_code
        == 201
    )
    membership_ids = list(
        db_session.scalars(
            select(ProjectMember.id)
            .join(Project, Project.id == ProjectMember.project_id)
            .where(Project.key == "DEV", ProjectMember.role == "PROJECT_ADMIN")
        )
    )
    db_session.rollback()
    raw_token = client.cookies.get(get_settings().session.cookie_name)

    def demote(member_id):
        """별도 session에서 관리자 역할 하향을 시도한다."""
        with db_session_factory() as session:
            actor = get_current_identity(session, raw_token)
            try:
                service.update_project_member_role(
                    session,
                    actor,
                    "DEV",
                    member_id,
                    MemberRoleUpdate(role="PROJECT_USER"),
                )
                return 200
            except AuthError as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(demote, membership_ids)) == [200, 409]
