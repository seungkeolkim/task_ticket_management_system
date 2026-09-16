import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    ("path", "expected_text"),
    [
        ("/", "좋은 오후예요"),
        ("/login", "워크스페이스에 로그인"),
        ("/account/password", "새 비밀번호 설정"),
        ("/projects", "내 프로젝트"),
        ("/projects/OPS/tickets", "저장 필터"),
        ("/projects/OPS/tickets/new", "새 티켓 만들기"),
        ("/projects/OPS/tickets/OPS-142", "티켓 관계"),
        ("/projects/OPS/tickets/OPS-142/edit", "티켓 편집"),
        ("/projects/OPS/board", "칸반 보드"),
        ("/projects/OPS/settings", "프로젝트 프로필"),
        ("/projects/OPS/members", "구성원과 역할"),
        ("/projects/OPS/trash", "프로젝트 휴지통"),
        ("/admin/users", "사용자 관리"),
        ("/admin/organizations", "조직 구조"),
        ("/admin/projects", "전체 프로젝트 관리"),
    ],
)
def test_mockup_page_is_available(
    client: TestClient,
    path: str,
    expected_text: str,
) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert expected_text in response.text


def test_root_is_the_unauthenticated_dashboard(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "화면 구조 검토용 목업" in response.text
    assert 'href="/projects/OPS/tickets/new"' in response.text


def test_mockup_static_styles_are_served(client: TestClient) -> None:
    response = client.get("/static/app.css")

    assert response.status_code == 200
    assert "--primary:" in response.text

