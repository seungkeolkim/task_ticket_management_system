from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select
from test_tickets import create_ticket, delete, login, patch, post
from test_tickets import ticket_people as ticket_people

from app.core.config import get_settings
from app.domain.auth import AuthError
from app.models import AuditLog, Project, ProjectMember, SavedFilter
from app.schemas.shared_filters import SharedFilterCreate
from app.services import shared_filters as service
from app.services.auth import get_current_identity

ENDPOINT = "/api/projects/DEV/shared-filters"


def create_shared_filter(client, name="팀 미완료", definition=None):
    """관리자로 공유 필터를 생성하고 검증된 응답을 반환한다."""
    login(client, "manager")
    response = post(client, ENDPOINT, {"name": name, "definition": definition or {}})
    assert response.status_code == 201
    return response.json()


def test_shared_filter_lifecycle_conflict_and_csrf(client, ticket_people, db_session):
    """조건 왕복·중복·CSRF·no-op·stale 방어와 감사 기록을 검증한다."""
    summary = create_shared_filter(
        client,
        definition={
            "types": ["TASK"],
            "created_from": "2026-10-03T15:00:00Z",
            "sort_by": "number",
            "page_size": 10,
        },
    )
    assert summary["visibility"] == "PROJECT"
    assert client.get(ENDPOINT).json() == [summary]
    endpoint = f"{ENDPOINT}/{summary['id']}"
    assert client.get(endpoint).json()["definition"]["types"] == ["TASK"]
    assert post(client, ENDPOINT, {"name": " 팀 미완료 ", "definition": {}}).status_code == 409
    assert client.post(ENDPOINT, json={"name": "CSRF", "definition": {}}).status_code == 403
    payload = {"expected_updated_at": summary["updated_at"], "name": "팀 미완료"}
    assert client.patch(endpoint, json=payload).status_code == 403
    assert (
        client.request(
            "DELETE", endpoint, json={"expected_updated_at": summary["updated_at"]}
        ).status_code
        == 403
    )
    assert patch(client, endpoint, payload).json() == summary
    renamed = patch(client, endpoint, payload | {"name": "팀 확인 대상"}).json()
    assert renamed["updated_at"] != summary["updated_at"]
    assert patch(client, endpoint, payload).status_code == 409
    assert (
        delete(client, endpoint, {"expected_updated_at": summary["updated_at"]}).status_code == 409
    )
    for view in ["tickets", "board"]:
        response = client.get(
            f"/projects/DEV/shared-filters/{summary['id']}/apply?view={view}",
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert f"/projects/DEV/{view}?" in response.headers["location"]
        assert "created_from=2026-10-04" in response.headers["location"]
        assert "page_size=10" in response.headers["location"]
        assert client.get(response.headers["location"]).status_code == 200
    overwritten = patch(
        client,
        endpoint,
        {
            "expected_updated_at": renamed["updated_at"],
            "definition": {"statuses": ["TODO"]},
        },
    ).json()
    assert client.get(endpoint).json()["definition"]["statuses"] == ["TODO"]
    assert (
        delete(client, endpoint, {"expected_updated_at": overwritten["updated_at"]}).status_code
        == 204
    )
    assert client.get(endpoint).status_code == 404
    events = db_session.scalars(
        select(AuditLog).where(AuditLog.target_type == "saved_filter")
    ).all()
    assert [event.action for event in events] == [
        "shared_filter.created",
        "shared_filter.updated",
        "shared_filter.updated",
        "shared_filter.deleted",
    ]
    assert all("팀" not in str(event.details) for event in events)


@pytest.mark.parametrize(
    "login_id, read_status, write_status",
    [
        ("member", 200, 403),
        ("guest", 200, 403),
        ("outsider", 404, 404),
    ],
)
def test_shared_filter_role_permissions(client, ticket_people, login_id, read_status, write_status):
    """구성원·게스트는 적용만 가능하고 비참여자는 공유 필터 존재를 알 수 없다."""
    summary = create_shared_filter(client)
    endpoint = f"{ENDPOINT}/{summary['id']}"
    login(client, login_id)
    assert client.get(ENDPOINT).status_code == read_status
    assert client.get(endpoint).status_code == read_status
    assert (
        client.get(f"/projects/DEV/shared-filters/{summary['id']}/apply").status_code == read_status
    )
    assert post(client, ENDPOINT, {"name": "조작", "definition": {}}).status_code == write_status
    revision = {"expected_updated_at": summary["updated_at"]}
    assert patch(client, endpoint, revision | {"name": "조작"}).status_code == write_status
    assert delete(client, endpoint, revision).status_code == write_status
    if read_status == 200:
        page = client.get("/projects/DEV/board").text
        assert "data-shared-filter-id=" in page
        assert "data-shared-filter-create" not in page


def test_shared_filter_project_scope_and_private_isolation(client, ticket_people, db_session):
    """개인 이름과 공유 이름은 독립적이며 다른 프로젝트 row를 조회·변경하지 못한다."""
    people, project = ticket_people
    personal = post(
        client,
        "/api/projects/DEV/personal-filters",
        {
            "name": "팀 미완료",
            "definition": {},
        },
    ).json()
    summary = create_shared_filter(client)
    assert client.get(f"{ENDPOINT}/{personal['id']}").status_code == 404
    assert client.get(f"/api/projects/DEV/personal-filters/{summary['id']}").status_code == 404
    other_project = Project(key="OTHER", name="다른 프로젝트", created_by_id=people["sysadmin"].id)
    db_session.add(other_project)
    db_session.flush()
    other_filter = SavedFilter(
        project_id=other_project.id,
        owner_id=people["manager"].id,
        visibility="PROJECT",
        name="다른 팀",
        definition={},
    )
    db_session.add(other_filter)
    db_session.commit()
    login(client, "sysadmin")
    endpoint = f"{ENDPOINT}/{other_filter.id}"
    assert client.get(endpoint).status_code == 404
    revision = {"expected_updated_at": other_filter.updated_at.isoformat()}
    assert patch(client, endpoint, revision | {"name": "유출"}).status_code == 404
    assert delete(client, endpoint, revision).status_code == 404
    assert len(client.get(ENDPOINT).json()) == 1


def test_shared_filter_survives_creator_removal_and_rechecks_roles(
    client, ticket_people, db_session
):
    """공유 필터는 생성자 소유가 아니며 현재 관리자와 구성원 권한으로 유지한다."""
    people, project = ticket_people
    summary = create_shared_filter(client)
    endpoint = f"{ENDPOINT}/{summary['id']}"
    membership = db_session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == people["manager"].id,
        )
    )
    membership.role = "PROJECT_USER"
    db_session.commit()
    revision = {"expected_updated_at": summary["updated_at"]}
    assert patch(client, endpoint, revision | {"name": "권한 회수"}).status_code == 403
    db_session.delete(membership)
    people["manager"].is_active = False
    db_session.commit()
    login(client, "member")
    assert client.get(endpoint).status_code == 200
    login(client, "sysadmin")
    changed = patch(client, endpoint, revision | {"name": "새 관리자 관리"})
    assert changed.status_code == 200
    assert db_session.get(SavedFilter, summary["id"]).owner_id == people["manager"].id
    events = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "project.override_access")
    ).all()
    assert any(event.details.get("permission") == "manage" for event in events)
    assert (
        delete(client, endpoint, {"expected_updated_at": changed.json()["updated_at"]}).status_code
        == 204
    )


@pytest.mark.parametrize("login_id", ["manager", "sysadmin"])
def test_inactive_project_shared_filters_are_read_only(client, ticket_people, db_session, login_id):
    """비활성 프로젝트는 관리자도 공유 필터를 변경하지 못하고 개인 선호는 유지한다."""
    _, project = ticket_people
    summary = create_shared_filter(client)
    project.is_active = False
    db_session.commit()
    login(client, login_id)
    endpoint = f"{ENDPOINT}/{summary['id']}"
    assert client.get(endpoint).status_code == 200
    assert post(client, ENDPOINT, {"name": "새 공유", "definition": {}}).status_code == 409
    revision = {"expected_updated_at": summary["updated_at"]}
    assert patch(client, endpoint, revision | {"name": "변경"}).status_code == 409
    assert delete(client, endpoint, revision).status_code == 409
    assert "data-shared-filter-create" not in client.get("/projects/DEV/tickets").text
    assert (
        post(
            client,
            "/api/projects/DEV/personal-filters",
            {
                "name": "개인 선호",
                "definition": {},
            },
        ).status_code
        == 201
    )


def test_shared_filter_reference_revalidation_and_repair(client, ticket_people, db_session):
    """저장 후 삭제된 계층 참조·지원하지 않는 schema를 거부하고 관리자가 복구한다."""
    epic = create_ticket(client, type="EPIC").json()
    summary = create_shared_filter(client, definition={"epic_id": epic["id"]})
    endpoint = f"{ENDPOINT}/{summary['id']}"
    saved_filter = db_session.get(SavedFilter, summary["id"])
    saved_filter.definition = {"epic_id": 999999}
    db_session.commit()
    assert client.get(endpoint).status_code == 409
    assert client.get(f"/projects/DEV/shared-filters/{summary['id']}/apply").status_code == 409
    saved_filter.schema_version = 9
    db_session.commit()
    assert client.get("/projects/DEV/tickets").status_code == 200
    current = client.get(ENDPOINT).json()[0]
    assert (
        patch(
            client,
            endpoint,
            {"expected_updated_at": current["updated_at"], "definition": {"epic_id": 999999}},
        ).status_code
        == 400
    )
    assert (
        patch(
            client, endpoint, {"expected_updated_at": current["updated_at"], "definition": {}}
        ).status_code
        == 200
    )
    assert client.get(endpoint).status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {"name": " ", "definition": {}},
        {"name": "공유", "definition": {}, "owner_id": 1},
        {"name": "공유", "definition": {}, "visibility": "PERSONAL"},
        {"name": "공유", "definition": {"sql": "SELECT * FROM users"}},
    ],
)
def test_shared_filter_rejects_forged_input(client, ticket_people, payload):
    """공개 범위·소유권·임의 SQL 등 허용되지 않은 입력을 거부한다."""
    login(client, "manager")
    assert post(client, ENDPOINT, payload).status_code == 422


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
def test_shared_filter_audit_failure_rolls_back(
    client, ticket_people, db_session, monkeypatch, operation
):
    """각 변경에서 감사 기록 실패 시 필터 변경도 함께 rollback한다."""
    summary = create_shared_filter(client)
    endpoint = f"{ENDPOINT}/{summary['id']}"

    def fail_audit(*arguments):
        """감사 저장 실패를 주입한다."""
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(service, "record_shared_filter_audit", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        if operation == "create":
            post(client, ENDPOINT, {"name": "실패", "definition": {}})
        elif operation == "update":
            patch(client, endpoint, {"expected_updated_at": summary["updated_at"], "name": "실패"})
        else:
            delete(client, endpoint, {"expected_updated_at": summary["updated_at"]})
    assert client.get(ENDPOINT).json() == [summary]


def test_shared_filter_concurrent_duplicate_creation(client, ticket_people, db_session_factory):
    """관리자 동시 생성에서 프로젝트 공유 이름 중복을 차단한다."""
    login(client, "manager")
    session_token = client.cookies.get(get_settings().session.cookie_name)

    def create_same_filter(attempt_number):
        """독립 session에서 동일 공유 이름 생성을 시도한다."""
        with db_session_factory() as session:
            actor = get_current_identity(session, session_token)
            try:
                service.create_shared_filter(
                    session,
                    actor,
                    "DEV",
                    SharedFilterCreate(
                        name="동시 공유",
                        definition={},
                    ),
                )
                return 201
            except AuthError as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(create_same_filter, range(2))) == [201, 409]
