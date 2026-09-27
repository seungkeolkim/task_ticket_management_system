from pathlib import Path

import pytest
from sqlalchemy import select

from app.domain.auth import hash_password
from app.main import app
from app.models import (
    Attachment,
    AuditLog,
    Organization,
    Project,
    ProjectMember,
    Ticket,
    TicketHistory,
    User,
)
from app.services import attachments as attachment_service
from app.storage.attachments import LocalAttachmentStorage, get_attachment_storage

PASSWORD = "Attachment-test-password-123!"
ORIGIN = {"Origin": "http://testserver"}


def csrf_token(client) -> str:
    """현재 로그인 session의 CSRF token을 반환한다."""
    return client.get("/api/auth/csrf").json()["csrf_token"]


def api_post(client, path: str, payload: dict[str, object]):
    """CSRF 보호가 적용된 JSON POST 요청을 보낸다."""
    return client.post(
        path,
        json=payload,
        headers=ORIGIN | {"X-CSRF-Token": csrf_token(client)},
    )


def login(client, login_id: str) -> None:
    """지정한 테스트 사용자로 로그인한다."""
    client.cookies.clear()
    response = api_post(
        client,
        "/api/auth/login",
        {"login_id": login_id, "password": PASSWORD},
    )
    assert response.status_code == 200


@pytest.fixture
def attachment_storage(client, tmp_path: Path):
    """HTTP 요청에 격리된 local 첨부파일 저장소를 주입한다."""
    storage = LocalAttachmentStorage(str(tmp_path / "attachments"))
    app.dependency_overrides[get_attachment_storage] = lambda: storage
    try:
        yield storage
    finally:
        app.dependency_overrides.pop(get_attachment_storage, None)


@pytest.fixture
def attachment_people(client, db_session, attachment_storage):
    """첨부파일 권한 검증용 사용자·프로젝트·티켓을 생성한다."""
    organization = Organization(key="attachment-test", name="첨부파일 테스트 조직")
    db_session.add(organization)
    db_session.flush()
    password_hash = hash_password(PASSWORD)
    people = {}
    for login_id in ["manager", "member", "guest", "outsider"]:
        user = User(
            login_id=login_id,
            display_name=f"{login_id} 표시명",
            organization_id=organization.id,
            password_hash=password_hash,
            must_change_password=False,
        )
        db_session.add(user)
        people[login_id] = user
    db_session.flush()
    project = Project(key="DEV", name="첨부파일 프로젝트", created_by_id=people["manager"].id)
    db_session.add(project)
    db_session.flush()
    db_session.add_all(
        [
            ProjectMember(
                project_id=project.id,
                user_id=people["manager"].id,
                role="PROJECT_ADMIN",
            ),
            ProjectMember(project_id=project.id, user_id=people["member"].id),
            ProjectMember(
                project_id=project.id,
                user_id=people["guest"].id,
                role="PROJECT_GUEST",
            ),
        ]
    )
    db_session.commit()
    login(client, "member")
    ticket_response = api_post(
        client,
        "/api/projects/DEV/tickets",
        {"type": "TASK", "title": "첨부파일 대상", "priority": "MAJOR"},
    )
    assert ticket_response.status_code == 201
    return people, project, ticket_response.json()


def upload_pdf(client, ticket_key: str, expected_version: int, filename: str = "guide.pdf"):
    """테스트용 PDF 첨부파일 upload 요청을 보낸다."""
    return client.post(
        f"/api/projects/DEV/tickets/{ticket_key}/attachments",
        data={"expected_version": str(expected_version)},
        files={"file": (filename, b"%PDF-1.4\nattachment body", "application/pdf")},
        headers=ORIGIN | {"X-CSRF-Token": csrf_token(client)},
    )


def upload_png(client, ticket_key: str, expected_version: int, filename: str = "diagram.png"):
    """테스트용 PNG 첨부파일 upload 요청을 보낸다."""
    content = b"\x89PNG\r\n\x1a\ninline image"
    return client.post(
        f"/api/projects/DEV/tickets/{ticket_key}/attachments",
        data={"expected_version": str(expected_version)},
        files={"file": (filename, content, "image/png")},
        headers=ORIGIN | {"X-CSRF-Token": csrf_token(client)},
    )


def test_upload_list_and_download_attachment(
    client,
    db_session,
    attachment_people,
    attachment_storage,
) -> None:
    """업로드가 분산 경로·metadata·이력에 저장되고 권한 다운로드되는지 검증한다."""
    _, project, ticket = attachment_people

    upload_response = upload_pdf(client, ticket["key"], ticket["version"], "docs/guide.pdf")

    assert upload_response.status_code == 201
    result = upload_response.json()
    assert result["attachment"]["original_filename"] == "guide.pdf"
    assert result["ticket_version"] == ticket["version"] + 1

    db_session.expire_all()
    attachment = db_session.scalar(select(Attachment))
    assert attachment is not None
    assert attachment.storage_key.startswith(
        f"projects/{project.key}/tickets/{attachment.ticket_id}/"
    )
    storage_parts = attachment.storage_key.split("/")
    assert len(storage_parts[-3]) == 2 and len(storage_parts[-2]) == 2
    history = db_session.scalar(
        select(TicketHistory).where(TicketHistory.event_type == "CONTENT_CHANGED")
    )
    assert history is not None
    assert history.changes == [
        {"field": "attachments", "before": [], "after": [attachment.id]}
    ]
    audit = db_session.scalar(
        select(AuditLog).where(AuditLog.action == "attachment.created")
    )
    assert audit is not None and audit.target_id == str(attachment.id)

    list_response = client.get(f"/api/projects/DEV/tickets/{ticket['key']}/attachments")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [attachment.id]

    download_response = client.get(
        f"/api/projects/DEV/tickets/{ticket['key']}/attachments/{attachment.id}/download"
    )
    assert download_response.status_code == 200
    assert download_response.content == b"%PDF-1.4\nattachment body"
    assert "filename*=UTF-8''guide.pdf" in download_response.headers["content-disposition"]


def test_guest_can_download_but_cannot_upload(
    client,
    db_session,
    attachment_people,
) -> None:
    """게스트는 일반 첨부파일을 읽을 수 있지만 등록할 수 없는지 검증한다."""
    _, _, ticket = attachment_people
    upload_response = upload_pdf(client, ticket["key"], ticket["version"])
    attachment_id = upload_response.json()["attachment"]["id"]

    login(client, "guest")
    guest_download = client.get(
        f"/api/projects/DEV/tickets/{ticket['key']}/attachments/{attachment_id}/download"
    )
    guest_upload = upload_pdf(client, ticket["key"], ticket["version"] + 1)

    assert guest_download.status_code == 200
    assert guest_upload.status_code == 403
    assert db_session.scalar(select(Ticket).where(Ticket.key == ticket["key"])).version == 2


def test_ticket_detail_upload_form_uses_same_attachment_service(
    client,
    attachment_people,
) -> None:
    """티켓 상세 form으로 등록한 파일이 화면 목록과 다운로드 링크에 표시되는지 검증한다."""
    _, _, ticket = attachment_people

    upload_response = client.post(
        f"/projects/DEV/tickets/{ticket['key']}/attachments",
        data={
            "expected_version": str(ticket["version"]),
            "csrf_token": csrf_token(client),
        },
        files={"file": ("화면자료.pdf", b"%PDF-1.4\nweb form", "application/pdf")},
        headers=ORIGIN,
        follow_redirects=False,
    )

    assert upload_response.status_code == 303
    detail_response = client.get(f"/projects/DEV/tickets/{ticket['key']}")
    assert detail_response.status_code == 200
    assert "화면자료.pdf" in detail_response.text
    assert "/attachments/1/download" in detail_response.text


def test_uploaded_image_is_rendered_through_protected_inline_endpoint(
    client,
    attachment_people,
) -> None:
    """업로드 image가 본문 내부 ID로 저장되고 권한 endpoint에서 inline 표시되는지 검증한다."""
    _, _, ticket = attachment_people
    upload_response = upload_png(client, ticket["key"], ticket["version"], "업무흐름.png")
    upload_result = upload_response.json()
    attachment_id = upload_result["attachment"]["id"]
    image_document = {
        "type": "doc",
        "content": [
            {
                "type": "image",
                "attrs": {"attachmentId": attachment_id, "alt": "업무 흐름"},
            }
        ],
    }

    update_response = client.patch(
        f"/api/projects/DEV/tickets/{ticket['key']}",
        json={
            "title": ticket["title"],
            "description_document": image_document,
            "priority": ticket["priority"],
            "parent_key": None,
            "assignee_id": None,
            "due_date": None,
            "expected_version": upload_result["ticket_version"],
        },
        headers=ORIGIN | {"X-CSRF-Token": csrf_token(client)},
    )

    assert update_response.status_code == 200
    detail_response = client.get(f"/projects/DEV/tickets/{ticket['key']}")
    assert detail_response.status_code == 200
    assert 'aria-label="이미지 업로드"' in detail_response.text
    assert (
        f'data-rich-text-image-upload-url="/api/projects/DEV/tickets/{ticket["key"]}/attachments"'
        in detail_response.text
    )
    assert f'src="/attachments/{attachment_id}"' in detail_response.text
    assert "등록된 설명이 없습니다." not in detail_response.text
    inline_detail_response = client.get(
        f"/projects/DEV/tickets?selected={ticket['key']}"
    )
    assert inline_detail_response.status_code == 200
    assert f'src="/attachments/{attachment_id}"' in inline_detail_response.text

    image_response = client.get(f"/attachments/{attachment_id}")
    assert image_response.status_code == 200
    assert image_response.content == b"\x89PNG\r\n\x1a\ninline image"
    assert image_response.headers["content-type"] == "image/png"
    assert image_response.headers["content-disposition"].startswith("inline;")


def test_inline_image_endpoint_hides_non_images_and_unauthorized_projects(
    client,
    attachment_people,
) -> None:
    """inline endpoint가 일반 파일과 프로젝트 외부 사용자에게 attachment를 은폐하는지 검증한다."""
    _, _, ticket = attachment_people
    pdf_id = upload_pdf(client, ticket["key"], ticket["version"]).json()["attachment"]["id"]
    png_id = upload_png(client, ticket["key"], ticket["version"] + 1).json()["attachment"]["id"]

    assert client.get(f"/attachments/{pdf_id}").status_code == 404

    login(client, "outsider")
    assert client.get(f"/attachments/{png_id}").status_code == 404


def test_rejects_declared_or_actual_file_type_mismatch(
    client,
    db_session,
    attachment_people,
) -> None:
    """확장자·요청 MIME·실제 signature 불일치가 metadata를 남기지 않는지 검증한다."""
    _, _, ticket = attachment_people
    response = client.post(
        f"/api/projects/DEV/tickets/{ticket['key']}/attachments",
        data={"expected_version": str(ticket["version"])},
        files={"file": ("fake.pdf", b"plain text", "application/pdf")},
        headers=ORIGIN | {"X-CSRF-Token": csrf_token(client)},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "attachment_content_mismatch"
    assert db_session.scalar(select(Attachment)) is None


def test_project_outsider_cannot_discover_attachment(
    client,
    db_session,
    attachment_people,
) -> None:
    """프로젝트 미참여자가 첨부파일 존재 여부를 확인하지 못하는지 검증한다."""
    _, _, ticket = attachment_people
    upload_response = upload_pdf(client, ticket["key"], ticket["version"])
    attachment_id = upload_response.json()["attachment"]["id"]

    login(client, "outsider")
    response = client.get(
        f"/api/projects/DEV/tickets/{ticket['key']}/attachments/{attachment_id}/download"
    )

    assert response.status_code == 404


def test_stale_upload_removes_staged_blob(
    client,
    attachment_people,
    attachment_storage,
) -> None:
    """stale version으로 거부된 업로드가 staging 파일을 남기지 않는지 검증한다."""
    _, _, ticket = attachment_people
    upload_pdf(client, ticket["key"], ticket["version"])

    response = upload_pdf(client, ticket["key"], ticket["version"], "stale.pdf")

    assert response.status_code == 409
    staging_directory = Path(attachment_storage.staging_directory)
    assert not list(staging_directory.iterdir())


def test_database_failure_removes_committed_blob(
    client,
    db_session,
    attachment_people,
    attachment_storage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """blob 확정 후 DB transaction 실패가 최종 파일을 보상 삭제하는지 검증한다."""
    _, _, ticket = attachment_people

    def fail_audit_recording(*_args, **_kwargs) -> None:
        """DB commit 직전 실패 상황을 재현한다."""
        raise RuntimeError("forced audit failure")

    monkeypatch.setattr(
        attachment_service,
        "_record_attachment_audit_event",
        fail_audit_recording,
    )

    with pytest.raises(RuntimeError, match="forced audit failure"):
        upload_pdf(client, ticket["key"], ticket["version"], "rollback.pdf")

    db_session.expire_all()
    assert db_session.scalar(select(Attachment)) is None
    stored_files = [
        path
        for path in Path(attachment_storage.root_directory).rglob("*")
        if path.is_file()
    ]
    assert stored_files == []
