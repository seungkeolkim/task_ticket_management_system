import re
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.domain.auth import AuthError, hash_password, verify_password
from app.main import app
from app.models import AuditLog, Organization, User, UserSession
from app.schemas.administration import OrganizationCreate, OrganizationUpdate, UserUpdate
from app.services import administration as service
from app.services.auth import get_current_identity

PASSWORD = "Disposable-admin-12345!"
RESET_PASSWORD = "Reset-user-pass-67890!"
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


def login(client, login_id="admin", password=PASSWORD):
    """사용자 인증 후 session 정보를 반환한다."""
    return post(client, "/api/auth/login", {"login_id": login_id, "password": password})


@pytest.fixture
def admin(client, db_session):
    """관리 기능 테스트용 관리자 계정을 제공한다."""
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
    """관리 기능 테스트용 신규 사용자 정보를 제공한다."""
    return {
        "login_id": " New.User ",
        "display_name": " 새 사용자 ",
        "email": "",
        "organization_id": default_organization_id,
        "password": "New-user-pass-12345!",
        **overrides,
    }


def organization_update_payload(organization: Organization, **overrides):
    """조직 관리 API에 보낼 전체 수정 값을 구성한다."""
    return {
        "name": organization.name,
        "parent_id": organization.parent_id,
        "description": organization.description,
        "is_active": organization.is_active,
        **overrides,
    }


def user_update_payload(user: User, **overrides):
    """관리 기능 테스트용 사용자 수정 정보를 제공한다."""
    return {
        "display_name": user.display_name,
        "email": user.email,
        "organization_id": user.organization_id,
        "system_role": user.system_role,
        "is_active": user.is_active,
        **overrides,
    }


def create_managed_user(db_session, admin, **overrides):
    """관리 기능 테스트용 대상 사용자를 생성한다."""
    values = {
        "login_id": "managed.user",
        "display_name": "관리 대상",
        "email": "managed@example.com",
        "organization_id": admin.organization_id,
        "password_hash": hash_password("Managed-user-pass-12345!"),
        "must_change_password": False,
    }
    values.update(overrides)
    managed_user = User(**values)
    db_session.add(managed_user)
    db_session.commit()
    return managed_user


def test_organization_user_and_first_login_flow(client, admin, db_session):
    """조직·로그인·사용자 관련 동작을 검증한다."""
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


def test_organization_update_move_and_activation_rules(client, admin, db_session):
    """조직 이동·순환·중복·비활성 상위 정책과 감사 기록을 검증한다."""
    first_root = Organization(key="first", name="첫 본부")
    second_root = Organization(key="second", name="둘째 본부")
    db_session.add_all([first_root, second_root])
    db_session.flush()
    team = Organization(key="team", name="개발팀", parent_id=first_root.id)
    sibling = Organization(key="sibling", name="운영팀", parent_id=second_root.id)
    db_session.add_all([team, sibling])
    db_session.commit()

    moved = patch(
        client,
        f"/api/admin/organizations/{team.id}",
        organization_update_payload(
            team, name="플랫폼팀", parent_id=second_root.id, description="새 설명"
        ),
    )
    assert moved.status_code == 200
    assert moved.json()["name"] == "플랫폼팀"
    assert moved.json()["depth"] == 1
    db_session.refresh(team)
    assert team.parent_id == second_root.id
    assert team.description == "새 설명"
    audit_count = db_session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.target_type == "organization", AuditLog.target_id == str(team.id))
    )
    assert audit_count == 1
    assert (
        patch(
            client, f"/api/admin/organizations/{team.id}", organization_update_payload(team)
        ).status_code
        == 200
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.target_type == "organization", AuditLog.target_id == str(team.id))
        )
        == audit_count
    )

    for target_id, requested_parent_id in ((team.id, team.id), (second_root.id, team.id)):
        target = db_session.get(Organization, target_id)
        response = patch(
            client,
            f"/api/admin/organizations/{target_id}",
            organization_update_payload(target, parent_id=requested_parent_id),
        )
        assert response.status_code == 409
        assert response.json()["code"] == "organization_cycle"
    duplicate = patch(
        client,
        f"/api/admin/organizations/{team.id}",
        organization_update_payload(team, name="운영팀"),
    )
    assert duplicate.status_code == 409
    db_session.refresh(team)
    assert team.name == "플랫폼팀" and team.parent_id == second_root.id
    existing_member = create_managed_user(db_session, admin, organization_id=team.id)

    deactivated = patch(
        client,
        f"/api/admin/organizations/{second_root.id}",
        organization_update_payload(second_root, is_active=False),
    )
    assert deactivated.status_code == 200
    assert not deactivated.json()["selectable"]
    team_row = next(
        row for row in client.get("/api/admin/organizations").json() if row["id"] == team.id
    )
    assert not team_row["selectable"]
    with TestClient(app) as existing_member_client:
        assert (
            login(
                existing_member_client,
                existing_member.login_id,
                "Managed-user-pass-12345!",
            ).status_code
            == 200
        )
        assert existing_member_client.get("/").status_code == 200
    assert (
        patch(
            client,
            f"/api/admin/organizations/{team.id}",
            organization_update_payload(team, description="비활성 상위 아래 설명 수정"),
        ).status_code
        == 200
    )
    db_session.refresh(team)
    assert (
        post(
            client, "/api/admin/organizations", {"name": "신규 팀", "parent_id": team.id}
        ).status_code
        == 400
    )
    assert post(client, "/api/admin/users", new_user(team.id)).status_code == 400
    assert (
        patch(
            client,
            f"/api/admin/organizations/{team.id}",
            organization_update_payload(team, parent_id=first_root.id),
        ).status_code
        == 200
    )
    db_session.refresh(team)
    assert team.parent_id == first_root.id
    assert client.get("/api/auth/me").status_code == 200
    db_session.refresh(second_root)
    assert (
        patch(
            client,
            f"/api/admin/organizations/{second_root.id}",
            organization_update_payload(second_root, is_active=True),
        ).status_code
        == 200
    )
    actions = list(
        db_session.scalars(
            select(AuditLog.action)
            .where(
                AuditLog.target_type == "organization",
                AuditLog.target_id == str(second_root.id),
            )
            .order_by(AuditLog.id)
        )
    )
    assert actions == ["organization.deactivated", "organization.reactivated"]


def test_organization_update_web_csrf_and_audit_rollback(
    client, admin, db_session, db_session_factory, monkeypatch
):
    """화면 제출과 CSRF를 확인하고 감사 실패 때 조직 변경을 되돌린다."""
    organization = Organization(key="managed", name="관리 대상")
    db_session.add(organization)
    db_session.commit()
    page = client.get("/admin/organizations")
    assert f"/admin/organizations/{organization.id}/update" in page.text
    csrf_token = re.search('name="csrf_token" value="([^"]+)"', page.text).group(1)
    path = f"/admin/organizations/{organization.id}/update"
    values = {"name": "변경 조직", "parent_id": "", "description": "설명", "is_active": "true"}
    assert client.post(path, data=values, headers=ORIGIN).status_code == 403
    assert (
        client.post(
            path,
            data=values | {"is_active": "", "csrf_token": csrf_token},
            headers=ORIGIN,
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/admin/organizations/{organization.id}",
            json=organization_update_payload(organization),
            headers=ORIGIN,
        ).status_code
        == 403
    )
    response = client.post(
        path, data=values | {"csrf_token": csrf_token}, headers=ORIGIN, follow_redirects=False
    )
    assert response.status_code == 303
    db_session.refresh(organization)
    assert organization.name == "변경 조직"

    def fail_audit(*args, **kwargs):
        """감사 저장 실패를 재현한다."""
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(service, "record_audit_event", fail_audit)
    with db_session_factory() as session:
        identity = get_current_identity(
            session, client.cookies.get(get_settings().session.cookie_name)
        )
        with pytest.raises(RuntimeError, match="audit failure"):
            service.update_organization(
                session,
                identity,
                organization.id,
                OrganizationUpdate(
                    name="롤백 대상", parent_id=None, description="", is_active=True
                ),
                "127.0.0.1",
            )
    db_session.expire_all()
    organization = db_session.get(Organization, organization.id)
    assert organization.name == "변경 조직"


def test_organization_update_requires_administrator(client, admin, db_session):
    """일반 사용자는 조직 정보를 변경할 수 없다."""
    managed_user = create_managed_user(db_session, admin)
    with TestClient(app) as managed_client:
        assert (
            login(managed_client, managed_user.login_id, "Managed-user-pass-12345!").status_code
            == 200
        )
        response = patch(
            managed_client,
            f"/api/admin/organizations/{admin.organization_id}",
            organization_update_payload(db_session.get(Organization, admin.organization_id)),
        )
        assert response.status_code == 403


def test_user_update_deactivation_reactivation_and_session_revocation(client, admin, db_session):
    """사용자 수정·비활성화·재활성화와 session 폐기를 검증한다."""
    destination = Organization(key="destination", name="이동 조직")
    db_session.add(destination)
    db_session.commit()
    managed_user = create_managed_user(db_session, admin)
    with TestClient(app) as managed_client:
        assert (
            login(managed_client, managed_user.login_id, "Managed-user-pass-12345!").status_code
            == 200
        )
        updated = patch(
            client,
            f"/api/admin/users/{managed_user.id}",
            user_update_payload(
                managed_user,
                display_name="변경된 사용자",
                email="UPDATED@EXAMPLE.COM",
                organization_id=destination.id,
                system_role="SYSTEM_ADMIN",
            ),
        )
        assert updated.status_code == 200
        assert updated.json()["display_name"] == "변경된 사용자"
        assert updated.json()["email"] == "updated@example.com"
        assert updated.json()["organization_name"] == "이동 조직"
        db_session.refresh(managed_user)
        assert managed_user.system_role == "SYSTEM_ADMIN" and managed_user.is_active

        deactivated = patch(
            client,
            f"/api/admin/users/{managed_user.id}",
            user_update_payload(managed_user, is_active=False),
        )
        assert deactivated.status_code == 200
        assert not deactivated.json()["is_active"]
        assert deactivated.json()["deactivated_at"] is not None
        assert managed_client.get("/api/auth/me").status_code == 401
        assert (
            db_session.scalar(
                select(func.count())
                .select_from(UserSession)
                .where(UserSession.user_id == managed_user.id)
            )
            == 0
        )

        db_session.refresh(managed_user)
        reactivated = patch(
            client,
            f"/api/admin/users/{managed_user.id}",
            user_update_payload(managed_user, is_active=True),
        )
        assert reactivated.status_code == 200
        assert reactivated.json()["is_active"]
        assert reactivated.json()["deactivated_at"] is None

    actions = list(
        db_session.scalars(
            select(AuditLog.action)
            .where(AuditLog.target_type == "user", AuditLog.target_id == str(managed_user.id))
            .order_by(AuditLog.id)
        )
    )
    assert actions == ["user.updated", "user.deactivated", "user.reactivated"]
    update_audit = db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "user.updated",
            AuditLog.target_id == str(managed_user.id),
        )
    )
    assert set(update_audit.details["changed_fields"]) == {
        "display_name",
        "email",
        "organization_id",
        "system_role",
    }


def test_last_active_administrator_is_protected(client, admin, db_session):
    """마지막 활성 시스템 관리자의 강등과 비활성화를 차단한다."""
    for overrides in (
        {"system_role": "USER"},
        {"is_active": False},
    ):
        response = patch(
            client,
            f"/api/admin/users/{admin.id}",
            user_update_payload(admin, **overrides),
        )
        assert response.status_code == 409
        assert response.json()["code"] == "last_active_administrator"
        db_session.refresh(admin)
        assert admin.system_role == "SYSTEM_ADMIN" and admin.is_active

    second_administrator = create_managed_user(
        db_session,
        admin,
        login_id="second.admin",
        email="second-admin@example.com",
        system_role="SYSTEM_ADMIN",
    )
    response = patch(
        client,
        f"/api/admin/users/{admin.id}",
        user_update_payload(admin, system_role="USER"),
    )
    assert response.status_code == 200
    assert response.json()["system_role"] == "USER"
    db_session.refresh(second_administrator)
    assert second_administrator.is_active and second_administrator.system_role == "SYSTEM_ADMIN"


def test_concurrent_administrator_deactivation_keeps_one_active(
    client, admin, db_session, db_session_factory
):
    """동시 관리자 비활성화에서도 활성 관리자를 한 명 이상 유지한다."""
    second_administrator = create_managed_user(
        db_session,
        admin,
        login_id="concurrent.admin",
        email="concurrent-admin@example.com",
        system_role="SYSTEM_ADMIN",
    )
    first_token = client.cookies.get(get_settings().session.cookie_name)
    with TestClient(app) as second_client:
        assert (
            login(
                second_client, second_administrator.login_id, "Managed-user-pass-12345!"
            ).status_code
            == 200
        )
        second_token = second_client.cookies.get(get_settings().session.cookie_name)
        start_barrier = Barrier(2)

        def deactivate_target(token_value, target_user_id, target_values):
            """별도 transaction에서 상대 관리자를 비활성화한다."""
            with db_session_factory() as session:
                identity = get_current_identity(session, token_value)
                start_barrier.wait()
                try:
                    service.update_user(
                        session,
                        identity,
                        target_user_id,
                        UserUpdate(**(target_values | {"is_active": False})),
                        "127.0.0.1",
                    )
                    return 200
                except AuthError as error:
                    return error.status_code

        first_values = user_update_payload(admin)
        second_values = user_update_payload(second_administrator)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_attempt = pool.submit(
                deactivate_target,
                first_token,
                second_administrator.id,
                second_values,
            )
            second_attempt = pool.submit(
                deactivate_target,
                second_token,
                admin.id,
                first_values,
            )
            results = sorted((first_attempt.result(), second_attempt.result()))
    assert results == [200, 403]
    db_session.expire_all()
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.system_role == "SYSTEM_ADMIN", User.is_active.is_(True))
        )
        == 1
    )


def test_password_reset_revokes_sessions_and_forces_change(client, admin, db_session):
    """관리자 비밀번호 초기화가 session 폐기와 변경 강제를 적용하는지 검증한다."""
    managed_user = create_managed_user(db_session, admin)
    with TestClient(app) as managed_client:
        assert (
            login(managed_client, managed_user.login_id, "Managed-user-pass-12345!").status_code
            == 200
        )
        reset = post(
            client,
            f"/api/admin/users/{managed_user.id}/password-reset",
            {"temporary_password": RESET_PASSWORD, "confirmation": RESET_PASSWORD},
        )
        assert reset.status_code == 200
        assert reset.json()["must_change_password"]
        assert RESET_PASSWORD not in reset.text
        assert managed_client.get("/api/auth/me").status_code == 401
        assert (
            login(managed_client, managed_user.login_id, "Managed-user-pass-12345!").status_code
            == 401
        )
        new_login = login(managed_client, managed_user.login_id, RESET_PASSWORD)
        assert new_login.status_code == 200
        assert new_login.json()["must_change_password"]

    db_session.refresh(managed_user)
    assert verify_password(RESET_PASSWORD, managed_user.password_hash)
    reset_audit = db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "user.password_reset",
            AuditLog.target_id == str(managed_user.id),
        )
    )
    assert reset_audit is not None and reset_audit.actor_user_id == admin.id


def test_user_update_and_password_reset_validation(client, admin, db_session):
    """사용자 수정·비밀번호 초기화의 중복·조직·확인값 검증을 확인한다."""
    managed_user = create_managed_user(db_session, admin)
    other_user = create_managed_user(
        db_session,
        admin,
        login_id="other.user",
        email="other@example.com",
    )
    inactive_organization = Organization(
        key="inactive-update", name="비활성 이동 조직", is_active=False
    )
    db_session.add(inactive_organization)
    db_session.commit()

    duplicate_email = patch(
        client,
        f"/api/admin/users/{managed_user.id}",
        user_update_payload(managed_user, email=other_user.email),
    )
    assert duplicate_email.status_code == 409
    invalid_organization = patch(
        client,
        f"/api/admin/users/{managed_user.id}",
        user_update_payload(managed_user, organization_id=inactive_organization.id),
    )
    assert invalid_organization.status_code == 400
    mismatch = post(
        client,
        f"/api/admin/users/{managed_user.id}/password-reset",
        {"temporary_password": RESET_PASSWORD, "confirmation": "Different-pass-12345!"},
    )
    assert mismatch.status_code == 422
    db_session.refresh(managed_user)
    assert verify_password("Managed-user-pass-12345!", managed_user.password_hash)


def test_user_lifecycle_api_requires_admin_and_csrf(client, admin, db_session):
    """사용자 lifecycle API의 관리자 권한과 CSRF 검증을 확인한다."""
    managed_user = create_managed_user(db_session, admin)
    update_payload = user_update_payload(managed_user, display_name="권한 검증 변경")
    reset_payload = {
        "temporary_password": RESET_PASSWORD,
        "confirmation": RESET_PASSWORD,
    }
    assert (
        client.patch(
            f"/api/admin/users/{managed_user.id}", json=update_payload, headers=ORIGIN
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/admin/users/{managed_user.id}/password-reset",
            json=reset_payload,
            headers=ORIGIN,
        ).status_code
        == 403
    )
    admin.system_role = "USER"
    db_session.commit()
    assert patch(client, f"/api/admin/users/{managed_user.id}", update_payload).status_code == 403
    assert (
        post(
            client,
            f"/api/admin/users/{managed_user.id}/password-reset",
            reset_payload,
        ).status_code
        == 403
    )


def test_user_management_web_forms_are_connected(client, admin, db_session):
    """사용자 수정과 비밀번호 초기화 web form 연결을 검증한다."""
    managed_user = create_managed_user(db_session, admin)
    page = client.get("/admin/users")
    csrf = re.search('name="csrf_token" value="([^"]+)"', page.text).group(1)
    assert f'action="/admin/users/{managed_user.id}/update"' in page.text
    assert f'action="/admin/users/{managed_user.id}/password-reset"' in page.text
    update_response = client.post(
        f"/admin/users/{managed_user.id}/update",
        data={
            "display_name": "화면 변경 사용자",
            "email": managed_user.email,
            "organization_id": managed_user.organization_id,
            "system_role": "USER",
            "is_active": "true",
            "csrf_token": csrf,
        },
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert update_response.status_code == 303
    assert f"updated={managed_user.id}" in update_response.headers["location"]
    reset_response = client.post(
        f"/admin/users/{managed_user.id}/password-reset",
        data={
            "temporary_password": RESET_PASSWORD,
            "confirmation": RESET_PASSWORD,
            "csrf_token": csrf,
        },
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert reset_response.status_code == 303
    assert f"password_reset={managed_user.id}" in reset_response.headers["location"]
    assert (
        client.post(f"/admin/users/{managed_user.id}/update", data={}, headers=ORIGIN).status_code
        == 403
    )


def test_user_deactivation_audit_failure_rolls_back_user_and_session(
    client, admin, db_session, db_session_factory, monkeypatch
):
    """비활성화 감사 실패 시 사용자와 session 변경을 함께 rollback한다."""
    managed_user = create_managed_user(db_session, admin)
    with TestClient(app) as managed_client:
        assert (
            login(managed_client, managed_user.login_id, "Managed-user-pass-12345!").status_code
            == 200
        )

        def fail(*args, **kwargs):
            """감사 저장 실패를 재현한다."""
            raise RuntimeError("simulated audit failure")

        monkeypatch.setattr(service, "record_audit_event", fail)
        raw_token = client.cookies.get(get_settings().session.cookie_name)
        with db_session_factory() as session:
            identity = get_current_identity(session, raw_token)
            target = session.get(User, managed_user.id)
            with pytest.raises(RuntimeError, match="audit failure"):
                service.update_user(
                    session,
                    identity,
                    target.id,
                    UserUpdate(**(user_update_payload(target) | {"is_active": False})),
                    "127.0.0.1",
                )
        db_session.expire_all()
        assert db_session.get(User, managed_user.id).is_active
        assert managed_client.get("/api/auth/me").status_code == 200


@pytest.mark.parametrize("path", ["/api/admin/users", "/api/admin/organizations"])
def test_permissions_and_csrf(client, admin, db_session, path):
    """CSRF·권한 관련 동작을 검증한다."""
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
    """CSRF 관련 동작을 검증한다."""
    assert client.post(path, data={}, headers=ORIGIN).status_code == 403
    admin.system_role = "USER"
    db_session.commit()
    assert client.get(path).status_code == 403
    assert client.post(path, data={}).status_code == 403
    with TestClient(app) as anonymous:
        assert anonymous.post(path, data={}, follow_redirects=False).status_code == 303


def test_duplicate_names_ids_emails_and_rollback(client, admin, db_session):
    """사용자·조직 중복 검증과 rollback을 확인한다."""
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
    """조직 관련 동작을 검증한다."""
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
    """사용자 관련 동작을 검증한다."""
    response = post(client, "/api/admin/users", new_user(admin.organization_id, **overrides))
    assert response.status_code in {400, 422}
    assert db_session.scalar(select(func.count()).select_from(User)) == 1


def test_form_preserves_safe_values_but_never_password(client, admin, db_session):
    """비밀번호 관련 동작을 검증한다."""
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
    """조직 관련 동작을 검증한다."""
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
    """검색 관련 동작을 검증한다."""
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
    """감사 로그 관련 동작을 검증한다."""

    def fail(*args, **kwargs):
        """실패 rollback 상황을 재현한다."""
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
    """조직·동시성 관련 동작을 검증한다."""
    raw_token = client.cookies.get(get_settings().session.cookie_name)

    def create(_):
        """동시성 테스트용 생성 시도를 수행한다."""
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
