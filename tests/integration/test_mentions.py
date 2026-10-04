"""본문 멘션의 lifecycle·권한·transaction 통합 검증."""

import pytest
from sqlalchemy import func, select
from test_comments import (
    api_delete,
    api_patch,
    api_post,
    comment_document,
    create_comment,
    create_ticket,
    login,
)
from test_comments import comment_people as comment_people

from app.models import Comment, Mention, ProjectMember, Ticket, TicketHistory
from app.services import comments as comment_service


def mention_document(user_id, *, label="입력된 이름", repeat=False):
    """사용자 ID로 참조하는 테스트 멘션 document를 구성한다."""
    mention = {"type": "mention", "attrs": {"userId": user_id, "label": label}}
    content = [mention, mention.copy()] if repeat else [mention]
    return {"type": "doc", "content": [{"type": "paragraph", "content": content}]}


def unread_mentions(client):
    """현재 로그인한 사용자의 대시보드 멘션을 조회한다."""
    return client.get("/api/dashboard").json()["mentions"]


def test_comment_mention_lifecycle(client, comment_people, db_session):
    """중복·no-op·읽음 보존·제거·재추가·삭제와 댓글 anchor를 검증한다."""
    people, _, _ = comment_people
    ticket = create_ticket(client)
    document = mention_document(people["guest"].id, repeat=True)
    comment = create_comment(client, ticket["key"], document).json()
    assert comment["body_schema_version"] == 3
    assert comment["body_plain_text"] == "@guest 표시명\n@guest 표시명"
    mention = db_session.scalar(select(Mention))
    mention_id = mention.id
    assert db_session.scalar(select(func.count()).select_from(Mention)) == 1
    endpoint = f"/api/projects/DEV/tickets/{ticket['key']}/comments/{comment['id']}"
    login(client, "guest")
    assert len(unread_mentions(client)) == 1
    assert client.post(f"/api/mentions/{mention_id}/read").status_code == 403
    response = api_post(client, f"/api/mentions/{mention_id}/read", {})
    assert response.json()["destination"].endswith(f"#comment-{comment['id']}")
    assert response.json()["read_count"] == 1
    assert api_post(client, f"/api/mentions/{mention_id}/read", {}).json()["read_count"] == 0
    login(client, "member")
    updated = api_patch(
        client, endpoint, {"body_document": document, "expected_version": comment["version"]}
    ).json()
    assert updated["version"] == comment["version"]
    updated = api_patch(
        client,
        endpoint,
        {
            "body_document": mention_document(people["guest"].id),
            "expected_version": updated["version"],
        },
    ).json()
    db_session.expire_all()
    assert db_session.get(Mention, mention_id).read_at is not None
    removed = api_patch(
        client,
        endpoint,
        {"body_document": comment_document("삭제한 멘션"), "expected_version": updated["version"]},
    ).json()
    db_session.expire_all()
    assert db_session.get(Mention, mention_id).removed_at is not None
    restored = api_patch(
        client, endpoint, {"body_document": document, "expected_version": removed["version"]}
    ).json()
    db_session.expire_all()
    assert db_session.get(Mention, mention_id).read_at is None
    assert db_session.get(Mention, mention_id).removed_at is None
    assert (
        api_delete(client, endpoint, {"expected_version": restored["version"]}).status_code == 204
    )
    login(client, "guest")
    assert unread_mentions(client) == []
    assert api_post(client, f"/api/mentions/{mention_id}/read", {}).status_code == 404


def test_description_mentions_and_history(client, comment_people, db_session):
    """새 티켓·편집·이력에 멘션을 기록하고 stale 쓰기는 거부한다."""
    people, _, _ = comment_people
    document = mention_document(people["manager"].id)
    response = api_post(
        client,
        "/api/projects/DEV/tickets",
        {
            "title": "설명 멘션",
            "description_document": document,
        },
    )
    assert response.status_code == 201
    ticket = response.json()
    assert ticket["body_schema_version"] == 3
    history = db_session.scalar(select(TicketHistory))
    assert history.after_state["body_schema_version"] == 3
    endpoint = f"/api/projects/DEV/tickets/{ticket['key']}"
    payload = {
        "title": "수정",
        "priority": "MAJOR",
        "description_document": comment_document("제거"),
        "expected_version": ticket["version"],
    }
    assert api_patch(client, endpoint, payload).status_code == 200
    assert api_patch(client, endpoint, payload).status_code == 409
    db_session.expire_all()
    assert db_session.scalar(select(Mention)).removed_at is not None
    assert db_session.get(Ticket, ticket["id"]).body_schema_version == 2


def test_candidates_and_target_permissions(client, comment_people, db_session):
    """후보에 비구성원·비활성 계정을 제외하고 위조된 대상 쓰기를 거부한다."""
    people, _, _ = comment_people
    endpoint = "/api/projects/DEV/mention-candidates"
    candidates = client.get(endpoint).json()
    assert {candidate["login_id"] for candidate in candidates} == {"manager", "member", "guest"}
    assert client.get(endpoint, params={"query": "guest"}).json()[0]["id"] == people["guest"].id
    assert client.get(endpoint, params={"query": "%"}).json() == []
    ticket = create_ticket(client)
    for login_id in ("outsider", "sysadmin"):
        assert (
            create_comment(client, ticket["key"], mention_document(people[login_id].id)).status_code
            == 422
        )
    people["guest"].is_active = False
    db_session.commit()
    assert (
        create_comment(client, ticket["key"], mention_document(people["guest"].id)).status_code
        == 422
    )
    login(client, "outsider")
    assert client.get(endpoint).status_code == 404
    login(client, "sysadmin")
    assert client.get(endpoint).status_code == 200


def test_read_all_visibility_and_ownership(client, comment_people, db_session):
    """페이지 제한 밖의 전체 읽음과 권한 회수·타인 접근 차단을 검증한다."""
    people, project, _ = comment_people
    ticket = create_ticket(client)
    for _ in range(7):
        create_comment(client, ticket["key"], mention_document(people["guest"].id))
    mention = db_session.scalar(select(Mention))
    login(client, "sysadmin")
    assert api_post(client, f"/api/mentions/{mention.id}/read", {}).status_code == 404
    login(client, "guest")
    assert len(unread_mentions(client)) == 5
    membership = db_session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id, ProjectMember.user_id == people["guest"].id
        )
    )
    db_session.delete(membership)
    db_session.commit()
    assert unread_mentions(client) == []
    assert api_post(client, "/api/mentions/read-all", {}).json()["read_count"] == 0
    assert api_post(client, f"/api/mentions/{mention.id}/read", {}).status_code == 404
    db_session.add(
        ProjectMember(project_id=project.id, user_id=people["guest"].id, role="PROJECT_GUEST")
    )
    project.is_active = False
    db_session.commit()
    assert api_post(client, "/api/mentions/read-all", {}).json()["read_count"] == 7
    assert unread_mentions(client) == []


def test_comment_audit_failure_rolls_back_mentions(client, comment_people, db_session, monkeypatch):
    """감사 실패 시 댓글과 멘션이 같은 transaction에서 rollback되는지 검증한다."""
    people, _, _ = comment_people
    ticket = create_ticket(client)

    def fail_audit(*arguments, **keywords):
        """감사 기록 장애를 주입한다."""
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(comment_service, "record_comment_audit_event", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        create_comment(client, ticket["key"], mention_document(people["guest"].id))
    assert db_session.scalar(select(func.count()).select_from(Mention)) == 0
    assert db_session.scalar(select(func.count()).select_from(Comment)) == 0


@pytest.mark.parametrize("invalid_id", [True, 0, -1, "1"])
def test_invalid_mention_node(client, comment_people, invalid_id):
    """멘션 ID 타입·범위가 잘못된 입력을 저장 전에 거부한다."""
    ticket = create_ticket(client)
    assert create_comment(client, ticket["key"], mention_document(invalid_id)).status_code == 422


def test_mention_migration_preserves_rows_and_converts_downgrade(
    client, comment_people, db_session, alembic_config, db_engine
):
    """멘션 본문·이력·댓글 self FK를 보존한 downgrade와 재적용을 검증한다."""
    from alembic import command
    from sqlalchemy import text

    people, _, _ = comment_people
    ticket = create_ticket(client)
    root = create_comment(client, ticket["key"], mention_document(people["guest"].id)).json()
    reply = api_post(
        client,
        f"/api/projects/DEV/tickets/{ticket['key']}/comments",
        {
            "body_document": mention_document(people["manager"].id),
            "parent_comment_id": root["id"],
        },
    ).json()
    db_session.close()
    with db_engine.connect() as connection:
        before = connection.execute(
            text("SELECT id, ticket_id, comment_id, target_user_id FROM mentions ORDER BY id")
        ).all()
    command.downgrade(alembic_config, "20261003_0007")
    with db_engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        assert (
            connection.execute(
                text("SELECT id, ticket_id, comment_id, target_user_id FROM mentions ORDER BY id")
            ).all()
            == before
        )
        assert (
            connection.execute(
                text("SELECT parent_comment_id FROM comments WHERE id=:id"), {"id": reply["id"]}
            ).scalar_one()
            == root["id"]
        )
        assert (
            connection.execute(
                text("SELECT body_schema_version FROM comments WHERE id=:id"), {"id": root["id"]}
            ).scalar_one()
            == 2
        )
    command.upgrade(alembic_config, "head")
    command.check(alembic_config)
    assert client.get(f"/api/projects/DEV/tickets/{ticket['key']}/comments").status_code == 200


def test_mention_read_audit_failure_and_trash_visibility(
    client, comment_people, db_session, monkeypatch
):
    """읽음 감사 실패를 rollback하고 휴지통 원본을 숨긴다."""
    from app.services import mentions as mention_service

    people, project, _ = comment_people
    ticket = create_ticket(client)
    create_comment(client, ticket["key"], mention_document(people["guest"].id))
    mention_id = db_session.scalar(select(Mention.id))
    login(client, "guest")

    def fail_audit(**keywords):
        """읽음 감사 객체 생성 실패를 주입한다."""
        raise RuntimeError("read audit unavailable")

    with monkeypatch.context() as context:
        context.setattr(mention_service, "AuditLog", fail_audit)
        with pytest.raises(RuntimeError, match="read audit unavailable"):
            api_post(client, f"/api/mentions/{mention_id}/read", {})
    db_session.expire_all()
    assert db_session.get(Mention, mention_id).read_at is None
    login(client, "member")
    response = api_delete(
        client,
        f"/api/projects/DEV/tickets/{ticket['key']}",
        {
            "expected_version": ticket["version"],
        },
    )
    assert response.status_code == 200
    login(client, "guest")
    assert unread_mentions(client) == []
    assert api_post(client, f"/api/mentions/{mention_id}/read", {}).status_code == 404


def test_mention_canonical_label_size_returns_validation_error(client, comment_people, db_session):
    """서버 표시 이름 확장으로 크기 제한을 넘으면 저장 없이 422를 반환한다."""
    people, _, _ = comment_people
    people["guest"].display_name = "a" * 100
    db_session.commit()
    ticket = create_ticket(client)
    document = mention_document(people["guest"].id, label="a")
    mention = document["content"][0]["content"][0]
    document["content"][0]["content"] = [mention] * 1000
    assert create_comment(client, ticket["key"], document).status_code == 422
    assert db_session.scalar(select(func.count()).select_from(Mention)) == 0
