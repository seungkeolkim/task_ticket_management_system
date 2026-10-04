"""본문 transaction에 결합되는 멘션 동기화와 본인 읽음 처리."""

import logging

from sqlalchemy.orm import Session

from app.db.types import utc_now
from app.domain.auth import AuthError, Identity
from app.domain.rich_text import iter_mention_nodes, validate_body_document
from app.models import AuditLog, Mention, Project, Ticket
from app.repositories import mentions as repository
from app.services import projects as project_service

logger = logging.getLogger(__name__)


def validate_mentions(session: Session, project_id: int, document: dict) -> None:
    """모든 멘션 대상의 현재 접근 권한과 표시 이름을 검증·정규화한다."""
    mention_nodes = list(iter_mention_nodes(document))
    if not mention_nodes:
        return
    requested_ids = {node["attrs"]["userId"] for node in mention_nodes}
    users = repository.eligible_users(session, project_id, user_ids=requested_ids)
    users_by_id = {user.id: user for user in users}
    if requested_ids != set(users_by_id):
        raise AuthError(
            "invalid_mention_target", "현재 프로젝트의 활성 구성원만 멘션할 수 있습니다.", 422
        )
    for node in mention_nodes:
        node["attrs"]["label"] = users_by_id[node["attrs"]["userId"]].display_name
    try:
        validate_body_document(document)
    except ValueError:
        raise AuthError(
            "invalid_mention_document",
            "멘션 표시 이름을 반영한 본문이 허용 범위를 초과했습니다.",
            422,
        ) from None


def synchronize_mentions(
    session: Session, actor_id: int, ticket, document: dict, comment_id: int | None = None
) -> None:
    """추가·제거 차이를 반영하며 유지된 멘션의 읽음 상태는 보존한다."""
    requested_ids = {node["attrs"]["userId"] for node in iter_mention_nodes(document)}
    existing = repository.source_mentions(session, ticket.id, comment_id)
    existing_by_user = {mention.target_user_id: mention for mention in existing}
    changed_at = utc_now()
    for mention in existing:
        if mention.target_user_id not in requested_ids and mention.removed_at is None:
            mention.removed_at = changed_at
    for target_user_id in sorted(requested_ids):
        mention = existing_by_user.get(target_user_id)
        if mention is None:
            session.add(
                Mention(
                    project_id=ticket.project_id,
                    ticket_id=ticket.id,
                    comment_id=comment_id,
                    target_user_id=target_user_id,
                    mentioned_by_id=actor_id,
                    created_at=changed_at,
                )
            )
        elif mention.removed_at is not None:
            mention.removed_at = None
            mention.read_at = None
            mention.created_at = changed_at
            mention.mentioned_by_id = actor_id


def list_candidates(session: Session, actor: Identity, project_key: str, query: str):
    """현재 프로젝트에 접근한 사용자에게 활성 구성원 후보만 반환한다."""
    with project_service.project_operation_context(session, actor, "mention_candidates"):
        project = project_service.require_project_member(session, actor, project_key)
        return [
            {"id": user.id, "display_name": user.display_name, "login_id": user.login_id}
            for user in repository.eligible_users(session, project.id, query=query.strip())
        ]


def mark_read(session: Session, actor: Identity, mention_id: int | None = None):
    """현재 접근 가능한 본인 멘션만 멱등적으로 확인하고 안전한 목적지를 반환한다."""
    changed_count = 0
    destination = "/"
    with project_service.project_operation_context(
        session, actor, "mention_read", write_operation=True
    ):
        project_service.is_system_administrator(session, actor)
        mentions = repository.inbox_mentions(session, actor.id, mention_id)
        if mention_id is not None and not mentions:
            raise AuthError("mention_not_found", "멘션을 찾을 수 없습니다.", 404)
        confirmed_at = utc_now()
        for mention in mentions:
            if mention.read_at is None:
                mention.read_at = confirmed_at
                changed_count += 1
            if mention_id is not None:
                project = session.get(Project, mention.project_id)
                ticket = session.get(Ticket, mention.ticket_id)
                destination = f"/projects/{project.key}/tickets/{ticket.key}"
                if mention.comment_id is not None:
                    destination += f"#comment-{mention.comment_id}"
        if changed_count:
            session.add(
                AuditLog(
                    action="mention.read",
                    actor_user_id=actor.id,
                    target_type="mention",
                    target_id=str(mention_id) if mention_id is not None else None,
                    details={"count": changed_count},
                )
            )
    logger.debug("mention_read actor_id=%s count=%s", actor.id, changed_count)
    return {"read_count": changed_count, "destination": destination}
