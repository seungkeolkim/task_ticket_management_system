"""조직 JSON export/import의 비파괴 왕복과 경합 방어를 검증한다."""

import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.domain.auth import hash_password
from app.models import AuditLog, Organization, User
from app.services import organization_transfer
from app.services.auth import get_current_identity

PASSWORD = "Disposable-admin-12345!"
ORIGIN = {"Origin": "http://testserver"}


def csrf_token(client: TestClient) -> str:
    """API 테스트용 session CSRF token을 읽는다."""
    return client.get("/api/auth/csrf").json()["csrf_token"]


def post_json(client: TestClient, path: str, payload: dict) -> object:
    """CSRF를 포함한 JSON POST를 보낸다."""
    return client.post(path, json=payload, headers=ORIGIN | {"X-CSRF-Token": csrf_token(client)})


def preview_json(client: TestClient, document: dict | bytes):
    """조직 JSON 원문으로 import 미리보기를 요청한다."""
    content = (
        document
        if isinstance(document, bytes)
        else json.dumps(document, ensure_ascii=False).encode()
    )
    return client.post(
        "/api/admin/organizations/import/preview",
        content=content,
        headers=ORIGIN | {"X-CSRF-Token": csrf_token(client), "Content-Type": "application/json"},
    )


def apply_json(client: TestClient, document: dict, preview_token: str):
    """미리보기 token과 조직 문서를 함께 적용한다."""
    return post_json(
        client,
        "/api/admin/organizations/import/apply",
        {"document_json": json.dumps(document, ensure_ascii=False), "preview_token": preview_token},
    )


def organization_node(key: str, name: str, children: list[dict] | None = None, **values):
    """테스트용 v1 조직 노드를 구성한다."""
    return {
        "key": key,
        "name": name,
        "description": values.get("description", ""),
        "is_active": values.get("is_active", True),
        "children": children or [],
    }


def document(*organizations: dict) -> dict:
    """테스트용 v1 조직 문서를 구성한다."""
    return {"schema_version": 1, "organizations": list(organizations)}


@pytest.fixture
def admin(client, db_session):
    """조직 transfer 테스트용 관리자 session을 생성한다."""
    root = Organization(key="root", name="기본 조직")
    db_session.add(root)
    db_session.flush()
    actor = User(
        login_id="admin",
        display_name="관리자",
        organization_id=root.id,
        system_role="SYSTEM_ADMIN",
        password_hash=hash_password(PASSWORD),
        must_change_password=False,
    )
    db_session.add(actor)
    db_session.commit()
    assert (
        post_json(
            client,
            "/api/auth/login",
            {"login_id": "admin", "password": PASSWORD},
        ).status_code
        == 200
    )
    return actor


def test_export_round_trip_and_non_destructive_apply(client, admin, db_session):
    """한글 트리 왕복·key 갱신·사용자 연결·미포함 조직 보존을 검증한다."""
    root = db_session.get(Organization, admin.organization_id)
    team = Organization(key="team", name="개발팀", parent_id=root.id, description="기존 설명")
    omitted = Organization(key="omitted", name="운영팀", parent_id=root.id)
    db_session.add_all([team, omitted])
    db_session.flush()
    member = User(
        login_id="member",
        display_name="구성원",
        organization_id=team.id,
        password_hash=hash_password("Member-password-12345!"),
    )
    db_session.add(member)
    db_session.commit()

    exported = client.get("/api/admin/organizations/export")
    assert exported.status_code == 200
    assert exported.headers["content-disposition"].startswith("attachment;")
    exported_document = exported.json()
    assert exported_document["schema_version"] == 1
    assert "개발팀" in exported.text
    assert "users" not in exported.text and "password_hash" not in exported.text
    assert preview_json(client, exported_document).json()["unchanged_count"] == 3

    changed_document = document(
        organization_node(
            "root",
            "기본 조직",
            [
                organization_node("team", "플랫폼팀", description="새 설명"),
                organization_node("new", "신규팀"),
            ],
        )
    )
    preview = preview_json(client, changed_document)
    assert preview.status_code == 200
    preview_data = preview.json()
    assert preview_data["errors"] == []
    assert preview_data["add_count"] == 1
    assert preview_data["update_count"] == 1
    assert db_session.get(Organization, team.id).name == "개발팀"
    applied = apply_json(client, changed_document, preview_data["preview_token"])
    assert applied.status_code == 200
    assert applied.json() == {"added": 1, "updated": 1, "unchanged": 1}
    db_session.expire_all()
    assert db_session.get(Organization, team.id).name == "플랫폼팀"
    assert db_session.get(User, member.id).organization_id == team.id
    assert db_session.get(Organization, omitted.id).name == "운영팀"
    assert db_session.scalar(select(Organization).where(Organization.key == "new")) is not None
    actions = list(
        db_session.scalars(
            select(AuditLog.action).where(AuditLog.action == "organization.imported")
        )
    )
    assert actions == ["organization.imported", "organization.imported"]


def test_import_rejects_conflicts_and_reparents_existing_tree(client, admin, db_session):
    """기존 조직과의 이름 충돌을 검출하고 부모·자식 위치 교환을 적용한다."""
    root = db_session.get(Organization, admin.organization_id)
    child = Organization(key="child", name="개발팀", parent_id=root.id)
    db_session.add(child)
    db_session.commit()
    duplicate = preview_json(client, document(organization_node("other", "기본 조직")))
    assert duplicate.status_code == 200
    assert duplicate.json()["preview_token"] is None
    assert any("중복" in error for error in duplicate.json()["errors"])

    repeated_key = preview_json(
        client,
        document(
            organization_node(
                "root",
                "기본 조직",
                [organization_node("child", "개발팀", [organization_node("root", "기본 조직")])],
            )
        ),
    )
    assert repeated_key.status_code == 422
    assert repeated_key.json()["code"] == "duplicate_organization_key"

    inversion = document(
        organization_node("child", "개발팀", [organization_node("root", "기본 조직")])
    )
    preview = preview_json(client, inversion).json()
    assert preview["errors"] == []
    assert apply_json(client, inversion, preview["preview_token"]).status_code == 200
    db_session.refresh(root)
    db_session.refresh(child)
    assert root.parent_id == child.id and child.parent_id is None


@pytest.mark.parametrize(
    "content, expected_code",
    [
        (b"not json", "invalid_organization_json"),
        (b"[" * 1000, "invalid_organization_json"),
        (
            b'{"schema_version":1,"schema_version":1,"organizations":[]}',
            "invalid_organization_json",
        ),
        (b'{"schema_version":2,"organizations":[]}', "invalid_organization_schema"),
        (
            json.dumps(
                document(organization_node("same", "A"), organization_node("same", "B"))
            ).encode(),
            "duplicate_organization_key",
        ),
        (
            json.dumps(
                document(organization_node("one", "A"), organization_node("two", "A"))
            ).encode(),
            "duplicate_organization_name",
        ),
        (b"x" * (organization_transfer.MAX_DOCUMENT_BYTES + 1), "organization_import_too_large"),
    ],
    ids=[
        "invalid-json",
        "excessive-json-depth",
        "duplicate-field",
        "wrong-version",
        "duplicate-key",
        "duplicate-name",
        "too-large",
    ],
)
def test_import_document_validation(client, admin, content, expected_code):
    """잘못된 파일을 미리보기 단계에서 거부한다."""
    response = preview_json(client, content)
    assert response.status_code in {413, 422}
    assert response.json()["code"] == expected_code


def test_import_requires_preview_and_rejects_stale_state(client, admin, db_session):
    """미리보기 token 없이 적용하거나 이후 변경된 구조에 적용하지 않는다."""
    imported = document(organization_node("new", "신규팀"))
    preview = preview_json(client, imported).json()
    assert apply_json(client, imported, "0" * 64).status_code == 409
    assert (
        apply_json(
            client, document(organization_node("other", "다른 팀")), preview["preview_token"]
        ).status_code
        == 409
    )
    assert post_json(client, "/api/admin/organizations", {"name": "추가 조직"}).status_code == 201
    assert apply_json(client, imported, preview["preview_token"]).status_code == 409
    assert db_session.scalar(select(func.count()).select_from(Organization)) == 2


def test_import_recreates_inactive_subtree_and_blocks_inactive_existing_parent(
    client, admin, db_session
):
    """새 비활성 계층은 왕복하고 기존 비활성 부모 아래 신규 등록은 차단한다."""
    imported = document(
        organization_node(
            "inactive",
            "비활성 본부",
            [organization_node("nested", "기존 하위 팀")],
            is_active=False,
        )
    )
    preview = preview_json(client, imported).json()
    assert preview["errors"] == []
    assert apply_json(client, imported, preview["preview_token"]).status_code == 200
    db_session.expire_all()
    parent = db_session.scalar(select(Organization).where(Organization.key == "inactive"))
    child = db_session.scalar(select(Organization).where(Organization.key == "nested"))
    assert not parent.is_active and child.parent_id == parent.id
    exported = client.get("/api/admin/organizations/export").json()
    assert preview_json(client, exported).json()["unchanged_count"] == 3
    blocked = preview_json(
        client,
        document(
            organization_node(
                "inactive",
                "비활성 본부",
                [
                    organization_node("nested", "기존 하위 팀"),
                    organization_node("new", "신규 하위 팀"),
                ],
                is_active=False,
            )
        ),
    )
    assert blocked.status_code == 200
    assert blocked.json()["preview_token"] is None
    assert any("비활성" in error for error in blocked.json()["errors"])


def test_import_export_admin_permissions_and_api_csrf(client, admin, db_session):
    """조직 파일 작업에 관리자 권한과 API 쓰기 CSRF를 적용한다."""
    imported = document(organization_node("new", "신규 조직"))
    assert (
        client.post(
            "/api/admin/organizations/import/preview",
            content=json.dumps(imported).encode(),
            headers=ORIGIN,
        ).status_code
        == 403
    )
    normal_user = User(
        login_id="normal",
        display_name="일반 사용자",
        organization_id=admin.organization_id,
        password_hash=hash_password("Normal-password-12345!"),
        must_change_password=False,
    )
    db_session.add(normal_user)
    db_session.commit()
    with TestClient(client.app) as normal_client:
        assert (
            post_json(
                normal_client,
                "/api/auth/login",
                {"login_id": "normal", "password": "Normal-password-12345!"},
            ).status_code
            == 200
        )
        assert normal_client.get("/api/admin/organizations/export").status_code == 403
        assert normal_client.get("/admin/organizations/export").status_code == 403
        assert preview_json(normal_client, imported).status_code == 403
        assert apply_json(normal_client, imported, "0" * 64).status_code == 403


def test_web_import_preview_apply_and_csrf(client, admin, db_session):
    """화면의 업로드→미리보기→적용과 CSRF를 확인한다."""
    page = client.get("/admin/organizations")
    assert "/admin/organizations/export" in page.text
    assert client.get("/admin/organizations/export").status_code == 200
    token = re.search('name="csrf_token" value="([^"]+)"', page.text).group(1)
    imported = document(organization_node("web", "웹 조직"))
    json_text = json.dumps(imported, ensure_ascii=False)
    path = "/admin/organizations/import/preview"
    files = {"document_file": ("organizations.json", json_text.encode("utf-8"), "application/json")}
    assert client.post(path, files=files, headers=ORIGIN).status_code == 403
    preview = client.post(path, data={"csrf_token": token}, files=files, headers=ORIGIN)
    assert preview.status_code == 200
    assert "웹 조직" in preview.text
    preview_token = re.search('name="preview_token" value="([^"]+)"', preview.text).group(1)
    apply_path = "/admin/organizations/import/apply"
    values = {"document_json": json_text, "preview_token": preview_token, "csrf_token": token}
    assert (
        client.post(apply_path, data=values | {"csrf_token": ""}, headers=ORIGIN).status_code == 403
    )
    applied = client.post(apply_path, data=values, headers=ORIGIN, follow_redirects=False)
    assert applied.status_code == 303
    assert "imported=1" in applied.headers["location"]
    assert db_session.scalar(select(Organization).where(Organization.key == "web")) is not None


def test_import_audit_failure_rolls_back_every_organization(
    client, admin, db_session, db_session_factory, monkeypatch
):
    """감사 실패 시 추가와 갱신을 모두 rollback한다."""
    imported = document(
        organization_node("root", "이름 변경", [organization_node("new", "신규 조직")])
    )
    preview_token = preview_json(client, imported).json()["preview_token"]

    def fail_audit(*args, **kwargs):
        """감사 저장 실패를 재현한다."""
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(organization_transfer, "record_audit_event", fail_audit)
    with db_session_factory() as session:
        session_token = client.cookies[get_settings().session.cookie_name]
        identity = get_current_identity(session, session_token)
        with pytest.raises(RuntimeError, match="audit failure"):
            organization_transfer.apply_organization_import(
                session,
                identity,
                json.dumps(imported, ensure_ascii=False).encode("utf-8"),
                session_token,
                preview_token,
                "127.0.0.1",
            )
    db_session.expire_all()
    assert db_session.get(Organization, admin.organization_id).name == "기본 조직"
    assert db_session.scalar(select(Organization).where(Organization.key == "new")) is None
