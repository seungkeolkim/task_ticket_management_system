import json

import pytest
from sqlalchemy import event, func, select

from app.domain.auth import hash_password
from app.domain.rich_text import render_body_document_html
from app.models import (
    Attachment,
    AuditLog,
    Comment,
    Organization,
    Project,
    ProjectMember,
    Ticket,
    User,
)
from app.services import comments as comment_service

PASSWORD = "Comment-test-password-123!"
ORIGIN = {"Origin": "http://testserver"}


def comment_document(text: str = "") -> dict[str, object]:
    """테스트용 단락 하나의 댓글 document를 반환한다."""
    paragraph: dict[str, object] = {"type": "paragraph"}
    if text:
        paragraph["content"] = [{"type": "text", "text": text}]
    return {"type": "doc", "content": [paragraph]}


def formatted_comment_document(text: str) -> dict[str, object]:
    """굵게 mark가 포함된 댓글 document를 반환한다."""
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": text,
                        "marks": [{"type": "bold"}],
                    }
                ],
            }
        ],
    }


def image_comment_document(attachment_id: int) -> dict[str, object]:
    """내부 attachment image 하나만 포함한 댓글 document를 반환한다."""
    return {
        "type": "doc",
        "content": [
            {
                "type": "image",
                "attrs": {"attachmentId": attachment_id, "alt": ""},
            }
        ],
    }


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


def api_patch(client, path: str, payload: dict[str, object]):
    """CSRF 보호가 적용된 JSON PATCH 요청을 보낸다."""
    return client.patch(
        path,
        json=payload,
        headers=ORIGIN | {"X-CSRF-Token": csrf_token(client)},
    )


def api_delete(client, path: str, payload: dict[str, object]):
    """CSRF 보호가 적용된 JSON DELETE 요청을 보낸다."""
    return client.request(
        "DELETE",
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
def comment_people(client, db_session):
    """댓글 권한 테스트용 사용자와 두 프로젝트를 생성한다."""
    organization = Organization(key="comment-test", name="댓글 테스트 조직")
    db_session.add(organization)
    db_session.flush()
    password_hash = hash_password(PASSWORD)
    people = {}
    for login_id in ["sysadmin", "manager", "member", "guest", "outsider"]:
        user = User(
            login_id=login_id,
            display_name=f"{login_id} 표시명",
            organization_id=organization.id,
            password_hash=password_hash,
            must_change_password=False,
            system_role="SYSTEM_ADMIN" if login_id == "sysadmin" else "USER",
        )
        db_session.add(user)
        people[login_id] = user
    db_session.flush()

    project = Project(key="DEV", name="댓글 프로젝트", created_by_id=people["sysadmin"].id)
    other_project = Project(
        key="ALT",
        name="다른 댓글 프로젝트",
        created_by_id=people["sysadmin"].id,
    )
    db_session.add_all([project, other_project])
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
            ProjectMember(
                project_id=other_project.id,
                user_id=people["manager"].id,
                role="PROJECT_ADMIN",
            ),
        ]
    )
    db_session.commit()
    login(client, "member")
    return people, project, other_project


def create_ticket(client, *, title: str = "댓글 대상 티켓") -> dict[str, object]:
    """댓글 테스트 대상 티켓을 API로 생성한다."""
    response = api_post(
        client,
        "/api/projects/DEV/tickets",
        {
            "type": "TASK",
            "title": title,
            "description_document": comment_document("티켓 설명"),
            "priority": "MAJOR",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_comment(client, ticket_key: str, document: dict[str, object]):
    """댓글 생성 API 요청을 보낸다."""
    return api_post(
        client,
        f"/api/projects/DEV/tickets/{ticket_key}/comments",
        {"body_document": document},
    )


def test_comment_lifecycle_permissions_scope_and_audit(
    client,
    comment_people,
    db_session,
):
    """댓글 CRUD의 역할 권한, scope, no-op 및 감사 정보를 검증한다."""
    people, project, other_project = comment_people
    ticket = create_ticket(client)
    original_document = formatted_comment_document("첫 댓글")
    created_response = create_comment(client, ticket["key"], original_document)
    assert created_response.status_code == 201
    created_comment = created_response.json()
    assert created_comment["body_html"] == render_body_document_html(original_document)
    assert created_comment["author"]["login_id"] == "member"
    assert created_comment["version"] == 1

    login(client, "guest")
    guest_list = client.get(f"/api/projects/DEV/tickets/{ticket['key']}/comments")
    assert guest_list.status_code == 200
    assert [comment["id"] for comment in guest_list.json()] == [created_comment["id"]]
    guest_write = create_comment(client, ticket["key"], comment_document("게스트 쓰기"))
    assert guest_write.status_code == 403
    assert guest_write.json()["code"] == "project_write_required"

    login(client, "manager")
    updated_document = comment_document("관리자가 수정")
    update_response = api_patch(
        client,
        f"/api/projects/DEV/tickets/{ticket['key']}/comments/{created_comment['id']}",
        {"body_document": updated_document, "expected_version": 1},
    )
    assert update_response.status_code == 200
    assert update_response.json()["version"] == 2

    db_session.expire_all()
    audit_count_before_no_op = db_session.scalar(
        select(func.count(AuditLog.id)).where(AuditLog.action == "comment.updated")
    )
    no_op_response = api_patch(
        client,
        f"/api/projects/DEV/tickets/{ticket['key']}/comments/{created_comment['id']}",
        {"body_document": updated_document, "expected_version": 2},
    )
    assert no_op_response.status_code == 200
    assert no_op_response.json()["version"] == 2
    db_session.expire_all()
    assert (
        db_session.scalar(
            select(func.count(AuditLog.id)).where(AuditLog.action == "comment.updated")
        )
        == audit_count_before_no_op
    )

    administrator_comment = create_comment(
        client,
        ticket["key"],
        comment_document("관리자가 작성한 댓글"),
    ).json()
    login(client, "member")
    member_update_response = api_patch(
        client,
        f"/api/projects/DEV/tickets/{ticket['key']}/comments/{administrator_comment['id']}",
        {"body_document": comment_document("사용자가 수정"), "expected_version": 1},
    )
    assert member_update_response.status_code == 200
    member_delete_response = api_delete(
        client,
        f"/api/projects/DEV/tickets/{ticket['key']}/comments/{administrator_comment['id']}",
        {"expected_version": 2},
    )
    assert member_delete_response.status_code == 204

    other_ticket = Ticket(
        project_id=other_project.id,
        number=1,
        key="ALT-1",
        type="TASK",
        title="다른 프로젝트 티켓",
        creator_id=people["manager"].id,
    )
    db_session.add(other_ticket)
    db_session.flush()
    other_comment = Comment(
        project_id=other_project.id,
        ticket_id=other_ticket.id,
        author_id=people["manager"].id,
        body_document=comment_document("다른 프로젝트 댓글"),
    )
    db_session.add(other_comment)
    db_session.commit()
    login(client, "manager")
    scoped_response = api_patch(
        client,
        f"/api/projects/DEV/tickets/{ticket['key']}/comments/{other_comment.id}",
        {"body_document": comment_document("scope 우회"), "expected_version": 1},
    )
    assert scoped_response.status_code == 404
    assert scoped_response.json()["code"] == "comment_not_found"

    delete_response = api_delete(
        client,
        f"/api/projects/DEV/tickets/{ticket['key']}/comments/{created_comment['id']}",
        {"expected_version": 2},
    )
    assert delete_response.status_code == 204
    assert client.get(f"/api/projects/DEV/tickets/{ticket['key']}/comments").json() == []
    db_session.expire_all()
    deleted_comment = db_session.get(Comment, created_comment["id"])
    assert deleted_comment is not None
    assert deleted_comment.deleted_at is not None
    assert deleted_comment.deleted_by_id == people["manager"].id
    assert deleted_comment.body_document == updated_document

    comment_audits = list(
        db_session.scalars(
            select(AuditLog)
            .where(AuditLog.target_type == "comment")
            .order_by(AuditLog.id)
        )
    )
    assert [audit.action for audit in comment_audits] == [
        "comment.created",
        "comment.updated",
        "comment.created",
        "comment.updated",
        "comment.deleted",
        "comment.deleted",
    ]
    assert all("body_document" not in audit.details for audit in comment_audits)
    assert all(audit.details["project_id"] == project.id for audit in comment_audits)


def test_empty_and_attachment_only_comment_validation(client, comment_people, db_session):
    """빈 구조를 거부하고 같은 티켓의 image-only 댓글만 허용한다."""
    _, project, _ = comment_people
    ticket = create_ticket(client)
    empty_response = create_comment(client, ticket["key"], comment_document())
    assert empty_response.status_code == 422
    assert empty_response.json()["code"] == "empty_comment"
    whitespace_response = create_comment(client, ticket["key"], comment_document("   \n "))
    assert whitespace_response.status_code == 422
    assert whitespace_response.json()["code"] == "empty_comment"

    other_ticket = create_ticket(client, title="첨부 scope 비교 티켓")
    current_ticket_row = db_session.scalar(select(Ticket).where(Ticket.key == ticket["key"]))
    other_ticket_row = db_session.scalar(select(Ticket).where(Ticket.key == other_ticket["key"]))
    valid_attachment = Attachment(
        project_id=project.id,
        ticket_id=current_ticket_row.id,
        original_filename="valid.png",
        media_type="image/png",
        size_bytes=10,
        storage_key="comment-valid-image",
        uploaded_by_id=current_ticket_row.creator_id,
    )
    wrong_ticket_attachment = Attachment(
        project_id=project.id,
        ticket_id=other_ticket_row.id,
        original_filename="wrong.png",
        media_type="image/png",
        size_bytes=10,
        storage_key="comment-wrong-image",
        uploaded_by_id=current_ticket_row.creator_id,
    )
    db_session.add_all([valid_attachment, wrong_ticket_attachment])
    db_session.commit()

    image_response = create_comment(
        client,
        ticket["key"],
        image_comment_document(valid_attachment.id),
    )
    assert image_response.status_code == 201
    assert image_response.json()["body_plain_text"] == ""
    wrong_scope_response = create_comment(
        client,
        ticket["key"],
        image_comment_document(wrong_ticket_attachment.id),
    )
    assert wrong_scope_response.status_code == 400
    assert wrong_scope_response.json()["code"] == "invalid_comment_attachment"


def test_terminal_inactive_and_trashed_ticket_comment_rules(
    client,
    comment_people,
    db_session,
):
    """종료 티켓은 허용하고 비활성 프로젝트·휴지통 티켓은 차단한다."""
    _, project, _ = comment_people
    ticket = create_ticket(client)
    progress_response = api_post(
        client,
        f"/api/projects/DEV/tickets/{ticket['key']}/transitions",
        {"target_status": "IN_PROGRESS", "expected_version": 1},
    )
    done_response = api_post(
        client,
        f"/api/projects/DEV/tickets/{ticket['key']}/transitions",
        {
            "target_status": "DONE",
            "expected_version": progress_response.json()["version"],
        },
    )
    assert done_response.status_code == 200
    terminal_comment_response = create_comment(
        client,
        ticket["key"],
        comment_document("완료 후 기록"),
    )
    assert terminal_comment_response.status_code == 201

    project.is_active = False
    db_session.commit()
    inactive_response = create_comment(client, ticket["key"], comment_document("비활성 쓰기"))
    assert inactive_response.status_code == 409
    assert inactive_response.json()["code"] == "project_inactive"

    project.is_active = True
    db_session.commit()
    trash_response = api_delete(
        client,
        f"/api/projects/DEV/tickets/{ticket['key']}",
        {"expected_version": done_response.json()["version"]},
    )
    assert trash_response.status_code == 200
    trashed_list_response = client.get(
        f"/api/projects/DEV/tickets/{ticket['key']}/comments"
    )
    assert trashed_list_response.status_code == 404
    assert trashed_list_response.json()["code"] == "ticket_not_found"


def test_stale_write_and_audit_failure_roll_back_comment_change(
    client,
    comment_people,
    db_session,
    monkeypatch,
):
    """stale version과 감사 저장 실패가 댓글 변경 전체를 rollback하는지 검증한다."""
    _ = comment_people
    ticket = create_ticket(client)
    created_comment = create_comment(
        client,
        ticket["key"],
        comment_document("원본 댓글"),
    ).json()
    first_update = api_patch(
        client,
        f"/api/projects/DEV/tickets/{ticket['key']}/comments/{created_comment['id']}",
        {"body_document": comment_document("첫 수정"), "expected_version": 1},
    )
    assert first_update.status_code == 200
    stale_response = api_patch(
        client,
        f"/api/projects/DEV/tickets/{ticket['key']}/comments/{created_comment['id']}",
        {"body_document": comment_document("stale 수정"), "expected_version": 1},
    )
    assert stale_response.status_code == 409
    assert stale_response.json()["code"] == "comment_version_conflict"

    def fail_audit(*_args, **_kwargs):
        """감사 저장소 장애를 재현한다."""
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(comment_service, "record_comment_audit_event", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        api_patch(
            client,
            f"/api/projects/DEV/tickets/{ticket['key']}/comments/{created_comment['id']}",
            {"body_document": comment_document("rollback 수정"), "expected_version": 2},
        )

    db_session.expire_all()
    stored_comment = db_session.get(Comment, created_comment["id"])
    assert stored_comment.version == 2
    assert stored_comment.body_document == comment_document("첫 수정")


def test_system_administrator_comment_override_is_audited(
    client,
    comment_people,
    db_session,
):
    """미참여 시스템 관리자의 댓글 read·write override 감사를 검증한다."""
    _ = comment_people
    ticket = create_ticket(client)
    login(client, "sysadmin")
    list_response = client.get(f"/api/projects/DEV/tickets/{ticket['key']}/comments")
    assert list_response.status_code == 200
    create_response = create_comment(
        client,
        ticket["key"],
        comment_document("관리자 override 댓글"),
    )
    assert create_response.status_code == 201

    db_session.expire_all()
    override_permissions = list(
        db_session.scalars(
            select(AuditLog.details["permission"].as_string()).where(
                AuditLog.action == "project.override_access"
            )
        )
    )
    assert "read" in override_permissions
    assert "write" in override_permissions


def test_comment_html_forms_editor_labels_retention_and_csrf(
    client,
    comment_people,
):
    """댓글 HTML form, editor label, 입력 유지와 CSRF 방어를 검증한다."""
    _ = comment_people
    ticket = create_ticket(client)
    detail_response = client.get(f"/projects/DEV/tickets/{ticket['key']}")
    assert detail_response.status_code == 200
    assert 'data-rich-text-label="댓글 작성 편집기"' in detail_response.text
    assert (
        'data-rich-text-placeholder="업무 진행 상황이나 참고 내용을 입력하세요."'
        in detail_response.text
    )

    whitespace_json = json.dumps(comment_document("   "), ensure_ascii=False)
    invalid_response = client.post(
        f"/projects/DEV/tickets/{ticket['key']}/comments",
        data={
            "csrf_token": csrf_token(client),
            "body_document": whitespace_json,
        },
        headers=ORIGIN,
    )
    assert invalid_response.status_code == 422
    assert "댓글 내용을 입력하세요." in invalid_response.text
    assert whitespace_json.replace('"', "&#34;") in invalid_response.text

    missing_csrf_response = client.post(
        f"/projects/DEV/tickets/{ticket['key']}/comments",
        data={"body_document": json.dumps(comment_document("CSRF 없음"))},
        headers=ORIGIN,
    )
    assert missing_csrf_response.status_code == 403

    created_response = client.post(
        f"/projects/DEV/tickets/{ticket['key']}/comments",
        data={
            "csrf_token": csrf_token(client),
            "body_document": json.dumps(comment_document("HTML 댓글"), ensure_ascii=False),
        },
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert created_response.status_code == 303
    comment_list = client.get(
        f"/api/projects/DEV/tickets/{ticket['key']}/comments"
    ).json()
    comment_id = comment_list[0]["id"]
    edit_response = client.get(
        f"/projects/DEV/tickets/{ticket['key']}?edit_comment={comment_id}"
    )
    assert edit_response.status_code == 200
    assert 'data-rich-text-label="댓글 수정 편집기"' in edit_response.text
    assert 'name="expected_version" value="1"' in edit_response.text


def test_comment_list_query_count_does_not_grow_with_comment_count(
    client,
    comment_people,
    db_session,
    db_engine,
):
    """작성자 join 조회로 댓글 수에 비례한 N+1 query가 생기지 않는지 검증한다."""
    people, project, _ = comment_people
    ticket = create_ticket(client)
    ticket_row = db_session.scalar(select(Ticket).where(Ticket.key == ticket["key"]))
    db_session.add(
        Comment(
            project_id=project.id,
            ticket_id=ticket_row.id,
            author_id=people["member"].id,
            body_document=comment_document("첫 댓글"),
        )
    )
    db_session.commit()

    query_count = 0

    def count_query(*_args, **_kwargs):
        """실행된 SQL statement 수를 누적한다."""
        nonlocal query_count
        query_count += 1

    event.listen(db_engine, "before_cursor_execute", count_query)
    try:
        first_response = client.get(
            f"/api/projects/DEV/tickets/{ticket['key']}/comments"
        )
        assert first_response.status_code == 200
        first_query_count = query_count

        db_session.add_all(
            [
                Comment(
                    project_id=project.id,
                    ticket_id=ticket_row.id,
                    author_id=people["member"].id,
                    body_document=comment_document(f"추가 댓글 {index}"),
                )
                for index in range(12)
            ]
        )
        db_session.commit()
        query_count = 0
        many_response = client.get(
            f"/api/projects/DEV/tickets/{ticket['key']}/comments"
        )
        assert many_response.status_code == 200
        assert len(many_response.json()) == 13
        assert query_count == first_query_count
    finally:
        event.remove(db_engine, "before_cursor_execute", count_query)
