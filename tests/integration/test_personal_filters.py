from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select
from test_tickets import create_ticket, delete, login, patch, post
from test_tickets import ticket_people as ticket_people

from app.core.config import get_settings
from app.domain.auth import AuthError
from app.models import AuditLog, Project, ProjectMember, SavedFilter, Ticket
from app.schemas.personal_filters import PersonalFilterCreate
from app.services import personal_filters as service
from app.services.auth import get_current_identity

ENDPOINT = "/api/projects/DEV/personal-filters"


def test_personal_filter_lifecycle_and_date_roundtrip(client, ticket_people, db_session):
    """개인 조건의 생성·이름 변경·덮어쓰기·삭제 및 화면 적용을 검증한다."""
    people, _ = ticket_people
    ticket = create_ticket(client, title="필터 적용 대상").json()
    definition = {
        "types": ["TASK"],
        "statuses": ["TODO"],
        "creator_ids": [people["member"].id],
        "created_from": "2026-10-03T15:00:00Z",
        "created_before": "2026-10-04T15:00:00Z",
        "sort_by": "number",
        "sort_direction": "asc",
        "page_size": 10,
    }
    created = post(client, ENDPOINT, {"name": "  내 업무  ", "definition": definition})
    assert created.status_code == 201
    summary = created.json()
    assert summary["name"] == "내 업무" and summary["visibility"] == "PERSONAL"
    filter_url = f"{ENDPOINT}/{summary['id']}"
    assert client.get(ENDPOINT).json() == [summary]
    loaded = client.get(filter_url).json()
    assert loaded["definition"]["sort_by"] == "number"
    response = client.get(
        f"/projects/DEV/personal-filters/{summary['id']}/apply?view=board", follow_redirects=False
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert "created_from=2026-10-04" in location
    assert "created_through=2026-10-04" in location
    assert "sort_by=number" in location and "page_size=10" in location
    assert client.get(location).status_code == 200

    renamed = patch(
        client,
        filter_url,
        {
            "name": "개인 이름 변경",
            "expected_updated_at": summary["updated_at"],
        },
    ).json()
    assert renamed["updated_at"] != summary["updated_at"]
    assert client.get(filter_url).json()["definition"] == loaded["definition"]
    unchanged = patch(
        client,
        filter_url,
        {
            "name": renamed["name"],
            "expected_updated_at": renamed["updated_at"],
        },
    ).json()
    assert unchanged == renamed
    overwritten = patch(
        client,
        filter_url,
        {
            "definition": {"query": ticket["key"]},
            "expected_updated_at": renamed["updated_at"],
        },
    ).json()
    assert client.get(filter_url).json()["definition"]["query"] == ticket["key"]
    assert (
        delete(client, filter_url, {"expected_updated_at": renamed["updated_at"]}).status_code
        == 409
    )
    assert (
        delete(client, filter_url, {"expected_updated_at": overwritten["updated_at"]}).status_code
        == 204
    )
    assert client.get(filter_url).status_code == 404
    events = db_session.scalars(
        select(AuditLog).where(AuditLog.target_type == "saved_filter")
    ).all()
    assert [entry.action for entry in events] == [
        "personal_filter.created",
        "personal_filter.updated",
        "personal_filter.updated",
        "personal_filter.deleted",
    ]
    assert all("내 업무" not in str(entry.details) for entry in events)


def test_personal_filters_isolate_owners_projects_and_shared_records(
    client, ticket_people, db_session
):
    """관리자도 타인 개인 필터를 읽거나 변경하지 못하고 공유 row도 별개로 취급한다."""
    people, project = ticket_people
    summary = post(client, ENDPOINT, {"name": "비공개 조건", "definition": {}}).json()
    shared = SavedFilter(
        project_id=project.id,
        owner_id=people["member"].id,
        name="공용 row",
        visibility="PROJECT",
        definition={},
    )
    db_session.add(shared)
    db_session.commit()
    assert len(client.get(ENDPOINT).json()) == 1
    assert client.get(f"{ENDPOINT}/{shared.id}").status_code == 404
    for login_id in ["manager", "sysadmin", "guest"]:
        login(client, login_id)
        assert client.get(ENDPOINT).json() == []
        assert client.get(f"{ENDPOINT}/{summary['id']}").status_code == 404
        assert (
            patch(
                client,
                f"{ENDPOINT}/{summary['id']}",
                {
                    "name": "가로채기",
                    "expected_updated_at": summary["updated_at"],
                },
            ).status_code
            == 404
        )
        assert (
            delete(
                client,
                f"{ENDPOINT}/{summary['id']}",
                {
                    "expected_updated_at": summary["updated_at"],
                },
            ).status_code
            == 404
        )
    login(client, "member")
    membership = db_session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == people["member"].id,
        )
    )
    db_session.delete(membership)
    db_session.commit()
    assert client.get(ENDPOINT).status_code == 404
    assert client.get(f"/projects/DEV/personal-filters/{summary['id']}/apply").status_code == 404


def test_guest_and_inactive_project_allow_personal_preferences(client, ticket_people, db_session):
    """개인 조회 설정은 게스트·비활성 프로젝트에서도 저장하며 업무 권한은 확대하지 않는다."""
    _, project = ticket_people
    project.is_active = False
    db_session.commit()
    login(client, "guest")
    created = post(client, ENDPOINT, {"name": "내 읽기 설정", "definition": {}})
    assert created.status_code == 201
    assert client.get(f"{ENDPOINT}/{created.json()['id']}").status_code == 200
    assert create_ticket(client).status_code == 403


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "   ", "definition": {}},
        {"name": "a" * 201, "definition": {}},
        {"name": "숨김\u200b이름", "definition": {}},
        {"name": "필터", "definition": {}, "owner_id": 1},
        {"name": "필터", "definition": {}, "visibility": "PROJECT"},
        {"name": "필터", "definition": {"schema_version": 2}},
        {"name": "필터", "definition": {"sql": "SELECT * FROM users"}},
        {"name": "필터", "definition": {"types": ["UNKNOWN"]}},
        {"name": "필터", "definition": {"unassigned": True, "assignee_ids": [1]}},
    ],
)
def test_personal_filter_rejects_unsafe_input(client, ticket_people, payload):
    """소유권·공개 범위·임의 query를 주입하거나 잘못된 schema를 저장하지 못하게 한다."""
    assert post(client, ENDPOINT, payload).status_code == 422


def test_personal_filter_reference_revalidation_and_recovery(client, ticket_people, db_session):
    """다른 프로젝트 참조와 삭제된 조건을 차단하고 잘못된 저장 조건을 복구할 수 있다."""
    people, project = ticket_people
    hidden_project = Project(key="OTHER", name="다른 프로젝트", created_by_id=people["sysadmin"].id)
    db_session.add(hidden_project)
    db_session.flush()
    hidden_epic = Ticket(
        project_id=hidden_project.id,
        number=1,
        key="OTHER-1",
        type="EPIC",
        title="다른 Epic",
        creator_id=people["sysadmin"].id,
    )
    db_session.add(hidden_epic)
    db_session.commit()
    for definition in [
        {"epic_id": hidden_epic.id},
        {"parent_id": hidden_epic.id},
        {"assignee_ids": [people["outsider"].id]},
        {"created_from": "2026-10-04T00:00:00Z"},
        {"created_before": "0001-01-01T00:00:00+09:00"},
    ]:
        assert (
            post(client, ENDPOINT, {"name": "잘못된 조건", "definition": definition}).status_code
            == 400
        )
    summary = post(client, ENDPOINT, {"name": "복구 가능", "definition": {}}).json()
    saved_filter = db_session.get(SavedFilter, summary["id"])
    saved_filter.schema_version = 9
    db_session.commit()
    assert client.get(f"{ENDPOINT}/{summary['id']}").status_code == 409
    assert client.get("/projects/DEV/board").status_code == 200
    latest = client.get(ENDPOINT).json()[0]
    restored = patch(
        client,
        f"{ENDPOINT}/{summary['id']}",
        {
            "definition": {},
            "expected_updated_at": latest["updated_at"],
        },
    )
    assert restored.status_code == 200
    assert client.get(f"{ENDPOINT}/{summary['id']}").status_code == 200
    assert client.get(f"/projects/OTHER/personal-filters/{summary['id']}/apply").status_code == 404


def test_personal_filter_csrf_duplicate_and_stale_update(client, ticket_people):
    """CSRF·정규화 중복·오래된 수정 요청을 차단한다."""
    assert client.post(ENDPOINT, json={"name": "보호", "definition": {}}).status_code == 403
    summary = post(client, ENDPOINT, {"name": "내 조건", "definition": {}}).json()
    assert post(client, ENDPOINT, {"name": " 내 조건 ", "definition": {}}).status_code == 409
    filter_url = f"{ENDPOINT}/{summary['id']}"
    assert (
        client.patch(
            filter_url,
            json={
                "name": "변경",
                "expected_updated_at": summary["updated_at"],
            },
        ).status_code
        == 403
    )
    assert (
        patch(
            client,
            filter_url,
            {
                "name": "변경",
                "expected_updated_at": summary["updated_at"],
            },
        ).status_code
        == 200
    )
    assert (
        patch(
            client,
            filter_url,
            {
                "name": "오래된 변경",
                "expected_updated_at": summary["updated_at"],
            },
        ).status_code
        == 409
    )


def test_personal_filter_audit_failure_rolls_back(client, ticket_people, monkeypatch, db_session):
    """감사 기록 실패 시 개인 필터도 함께 rollback한다."""

    def fail_audit(*arguments):
        """감사 저장 실패를 재현한다."""
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(service, "record_personal_filter_audit", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        post(client, ENDPOINT, {"name": "롤백", "definition": {}})
    assert db_session.scalar(select(func.count()).select_from(SavedFilter)) == 0


def test_personal_filter_concurrent_duplicate_creation(client, ticket_people, db_session_factory):
    """동시 생성에서도 같은 소유 범위의 이름을 중복 저장하지 않는다."""
    session_token = client.cookies.get(get_settings().session.cookie_name)

    def create_same_filter(attempt_number):
        """독립 session에서 동일한 필터 생성을 시도한다."""
        with db_session_factory() as session:
            actor = get_current_identity(session, session_token)
            try:
                service.create_personal_filter(
                    session, actor, "DEV", PersonalFilterCreate(name="동시 생성", definition={})
                )
                return 201
            except AuthError as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(create_same_filter, range(2))) == [201, 409]
