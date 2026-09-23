import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.auth import hash_password
from app.models import Organization, Project, ProjectMember, User


@pytest.fixture
def authenticated_client(client: TestClient, db_session: Session) -> TestClient:
    organization = Organization(key="mockup-test", name="검증 조직")
    db_session.add(organization)
    db_session.flush()
    account = User(
        login_id="reviewer",
        display_name="검증 사용자",
        organization_id=organization.id,
        password_hash=hash_password("Mockup-test-pass1"),
        system_role="SYSTEM_ADMIN",
        must_change_password=False,
    )
    db_session.add(account)
    db_session.flush()
    project = Project(key="OPS", name="검증 프로젝트", created_by_id=account.id)
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMember(project_id=project.id, user_id=account.id, role="PROJECT_ADMIN"))
    db_session.commit()
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    result = client.post(
        "/api/auth/login",
        json={"login_id": "reviewer", "password": "Mockup-test-pass1"},
        headers={"Origin": "http://testserver", "X-CSRF-Token": token},
    )
    assert result.status_code == 200
    return client


@pytest.mark.parametrize(
    ("path", "expected_text"),
    [
        ("/", "좋은 하루예요"),
        ("/account/password", "새 비밀번호 설정"),
        ("/projects", "내 프로젝트"),
        ("/projects/OPS/tickets", "실제 프로젝트 데이터"),
        ("/projects/OPS/tickets/new", "새 티켓 만들기"),
        ("/projects/OPS/tickets/OPS-142/edit", "이 업무 기능은 준비 중"),
        ("/projects/OPS/board", "칸반 보드"),
        ("/projects/OPS/settings", "프로젝트 프로필"),
        ("/projects/OPS/members", "구성원과 역할"),
        ("/projects/OPS/trash", "이 업무 기능은 준비 중"),
        ("/admin/users", "사용자 관리"),
        ("/admin/organizations", "조직 구조"),
        ("/admin/projects", "전체 프로젝트 관리"),
    ],
)
def test_mockup_page_is_available(
    authenticated_client: TestClient,
    path: str,
    expected_text: str,
) -> None:
    response = authenticated_client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert expected_text in response.text


def test_unknown_live_ticket_returns_not_found(authenticated_client: TestClient) -> None:
    response = authenticated_client.get("/projects/OPS/tickets/OPS-142")

    assert response.status_code == 404
    assert response.json()["code"] == "ticket_not_found"


def test_root_redirects_to_login_when_unauthenticated(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=%2F"


def test_root_retains_authenticated_dashboard(authenticated_client: TestClient) -> None:
    client = authenticated_client
    response = client.get("/")

    assert response.status_code == 200
    assert "이 화면은 실제 데이터와 권한을 사용합니다." in response.text
    assert "검증 사용자" in response.text
    assert 'href="/tickets"' in response.text


def test_mockup_static_styles_are_served(client: TestClient) -> None:
    response = client.get("/static/app.css")

    assert response.status_code == 200
    assert "--primary:" in response.text
