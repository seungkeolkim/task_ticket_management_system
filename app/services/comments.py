"""댓글 조회·작성·수정·soft delete application service."""

import logging

from sqlalchemy.orm import Session

from app.db.types import utc_now
from app.domain.auth import AuthError, Identity
from app.domain.codes import ProjectRole
from app.domain.rich_text import (
    empty_body_document,
    extract_body_document_text,
    iter_attachment_ids,
    render_body_document_html,
)
from app.models import AuditLog, Comment
from app.repositories import comments as repository
from app.repositories import tickets as ticket_repository
from app.schemas.comments import (
    CommentAuthorView,
    CommentCreate,
    CommentDelete,
    CommentUpdate,
    CommentView,
)
from app.services import projects as project_service

logger = logging.getLogger(__name__)


def record_comment_audit_event(
    session: Session,
    action: str,
    actor_id: int,
    comment: Comment,
    *,
    before_version: int | None,
    after_version: int,
) -> None:
    """본문을 제외한 댓글 변경 감사 event를 기록한다."""
    session.add(
        AuditLog(
            action=action,
            actor_user_id=actor_id,
            target_type="comment",
            target_id=str(comment.id),
            details={
                "project_id": comment.project_id,
                "ticket_id": comment.ticket_id,
                "comment_id": comment.id,
                "parent_comment_id": comment.parent_comment_id,
                "before_version": before_version,
                "after_version": after_version,
            },
        )
    )


def uses_system_administrator_override(project) -> bool:
    """현재 프로젝트 접근이 시스템 관리자 override인지 반환한다."""
    return project.role is None and project.can_manage


def can_manage_comments(project) -> bool:
    """프로젝트에서 댓글 쓰기 권한을 사용할 수 있는지 반환한다."""
    return project.is_active and (
        project.role in {ProjectRole.ADMIN, ProjectRole.USER} or project.can_manage
    )


def build_comment_view(comment_row, *, depth: int) -> CommentView:
    """댓글과 작성자 row를 공통 renderer 기반 view로 변환한다."""
    comment = comment_row[0]
    mapping = comment_row._mapping
    is_deleted = comment.deleted_at is not None
    body_document = empty_body_document() if is_deleted else comment.body_document
    return CommentView(
        id=comment.id,
        project_id=comment.project_id,
        ticket_id=comment.ticket_id,
        parent_comment_id=comment.parent_comment_id,
        depth=depth,
        author=CommentAuthorView(
            id=mapping["author_id"],
            login_id=mapping["author_login_id"],
            display_name=mapping["author_display_name"],
        ),
        body_document=body_document,
        body_html="" if is_deleted else render_body_document_html(comment.body_document),
        body_plain_text="" if is_deleted else extract_body_document_text(comment.body_document),
        body_schema_version=comment.body_schema_version,
        version=comment.version,
        is_deleted=is_deleted,
        deleted_at=comment.deleted_at,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )


def build_threaded_comment_views(comment_rows) -> list[CommentView]:
    """원댓글 다음에 대댓글이 오도록 한 단계 thread view를 구성한다."""
    root_rows = []
    reply_rows_by_parent_id: dict[int, list] = {}
    for comment_row in comment_rows:
        comment = comment_row[0]
        if comment.parent_comment_id is None:
            root_rows.append(comment_row)
            continue
        reply_rows_by_parent_id.setdefault(comment.parent_comment_id, []).append(comment_row)

    threaded_comments = []
    for root_row in root_rows:
        root_comment = root_row[0]
        threaded_comments.append(build_comment_view(root_row, depth=0))
        for reply_row in reply_rows_by_parent_id.get(root_comment.id, []):
            threaded_comments.append(build_comment_view(reply_row, depth=1))
    return threaded_comments


def _require_active_project(project) -> None:
    """비활성 프로젝트의 댓글 쓰기를 거부한다."""
    if not project.is_active:
        raise AuthError(
            "project_inactive",
            "비활성 프로젝트의 댓글은 변경할 수 없습니다.",
            409,
        )


def _get_accessible_ticket(
    session: Session,
    actor: Identity,
    project,
    ticket_key: str,
):
    """프로젝트 접근 범위에서 삭제되지 않은 티켓을 조회한다."""
    ticket_row = ticket_repository.ticket_row(
        session,
        project.id,
        actor.id,
        ticket_key.strip().upper(),
        override=uses_system_administrator_override(project),
    )
    if ticket_row is None:
        raise AuthError("ticket_not_found", "티켓을 찾을 수 없습니다.", 404)
    return ticket_row[0]


def _get_active_comment_row(
    session: Session,
    actor: Identity,
    project,
    ticket_id: int,
    comment_id: int,
):
    """프로젝트·티켓 scope에서 삭제되지 않은 댓글을 조회한다."""
    comment_row = repository.active_comment_row(
        session,
        project.id,
        ticket_id,
        comment_id,
        actor.id,
        override=uses_system_administrator_override(project),
    )
    if comment_row is None:
        raise AuthError("comment_not_found", "댓글을 찾을 수 없습니다.", 404)
    return comment_row


def _get_reply_parent_row(
    session: Session,
    actor: Identity,
    project,
    ticket_id: int,
    parent_comment_id: int,
):
    """같은 티켓의 삭제되지 않은 원댓글만 대댓글 부모로 허용한다."""
    parent_row = repository.active_comment_row(
        session,
        project.id,
        ticket_id,
        parent_comment_id,
        actor.id,
        override=uses_system_administrator_override(project),
    )
    if parent_row is None:
        raise AuthError(
            "parent_comment_not_found",
            "답글 대상 댓글을 찾을 수 없습니다.",
            404,
        )
    if parent_row[0].parent_comment_id is not None:
        raise AuthError(
            "comment_reply_depth_exceeded",
            "대댓글에는 다시 답글을 등록할 수 없습니다.",
            422,
        )
    return parent_row


def _require_expected_version(comment: Comment, expected_version: int) -> None:
    """요청 version과 현재 댓글 version이 같은지 검증한다."""
    if comment.version != expected_version:
        raise AuthError(
            "comment_version_conflict",
            "다른 사용자가 먼저 댓글을 변경했습니다. 최신 내용을 다시 불러오세요.",
            409,
        )


def _validate_comment_body(
    session: Session,
    project_id: int,
    ticket_id: int,
    body_document: dict[str, object],
) -> None:
    """빈 댓글을 거부하고 image attachment의 티켓 scope를 검증한다."""
    plain_text = extract_body_document_text(body_document).strip()
    requested_attachment_ids = set(iter_attachment_ids(body_document))
    if not plain_text and not requested_attachment_ids:
        raise AuthError("empty_comment", "댓글 내용을 입력하세요.", 422)

    available_attachment_ids = repository.available_ticket_attachment_ids(
        session,
        project_id,
        ticket_id,
        requested_attachment_ids,
    )
    if requested_attachment_ids != available_attachment_ids:
        raise AuthError(
            "invalid_comment_attachment",
            "댓글에 현재 티켓에서 사용할 수 없는 첨부파일이 포함되어 있습니다.",
        )


def list_ticket_comments(
    session: Session,
    actor: Identity,
    project_key: str,
    ticket_key: str,
):
    """티켓의 삭제되지 않은 댓글을 작성 시각과 ID 순서로 조회한다."""
    with project_service.project_operation_context(session, actor, "comment_list"):
        project = project_service.require_project_member(session, actor, project_key)
        ticket = _get_accessible_ticket(session, actor, project, ticket_key)
        comment_rows = repository.list_comment_rows(
            session,
            project.id,
            ticket.id,
            actor.id,
            override=uses_system_administrator_override(project),
        )
        return project, ticket, build_threaded_comment_views(comment_rows)


def create_comment(
    session: Session,
    actor: Identity,
    project_key: str,
    ticket_key: str,
    payload: CommentCreate,
) -> CommentView:
    """권한과 본문을 검증해 티켓 댓글을 생성한다."""
    with project_service.project_operation_context(
        session,
        actor,
        "comment_create",
        write_operation=True,
        conflict_code="comment_conflict",
        conflict_message="댓글 생성 상태가 변경되었습니다. 다시 확인하세요.",
    ):
        project = project_service.require_project_user_access(session, actor, project_key)
        _require_active_project(project)
        ticket = _get_accessible_ticket(session, actor, project, ticket_key)
        if payload.parent_comment_id is not None:
            _get_reply_parent_row(
                session,
                actor,
                project,
                ticket.id,
                payload.parent_comment_id,
            )
        _validate_comment_body(
            session,
            project.id,
            ticket.id,
            payload.body_document,
        )
        comment = Comment(
            project_id=project.id,
            ticket_id=ticket.id,
            parent_comment_id=payload.parent_comment_id,
            author_id=actor.id,
            body_document=payload.body_document,
        )
        session.add(comment)
        session.flush()
        record_comment_audit_event(
            session,
            "comment.created",
            actor.id,
            comment,
            before_version=None,
            after_version=comment.version,
        )
        comment_row = _get_active_comment_row(
            session,
            actor,
            project,
            ticket.id,
            comment.id,
        )
        result = build_comment_view(
            comment_row,
            depth=1 if comment.parent_comment_id is not None else 0,
        )

    logger.info(
        "comment_created comment_id=%s project_id=%s ticket_id=%s",
        result.id,
        result.project_id,
        result.ticket_id,
    )
    return result


def update_comment(
    session: Session,
    actor: Identity,
    project_key: str,
    ticket_key: str,
    comment_id: int,
    payload: CommentUpdate,
) -> CommentView:
    """optimistic lock과 no-op 정책을 적용해 댓글 본문을 수정한다."""
    comment_changed = False
    with project_service.project_operation_context(
        session,
        actor,
        "comment_update",
        write_operation=True,
        conflict_code="comment_conflict",
        conflict_message="댓글 수정 상태가 변경되었습니다. 다시 확인하세요.",
        stale_code="comment_version_conflict",
        stale_message="다른 사용자가 먼저 댓글을 변경했습니다. 최신 내용을 다시 불러오세요.",
    ):
        project = project_service.require_project_user_access(session, actor, project_key)
        _require_active_project(project)
        ticket = _get_accessible_ticket(session, actor, project, ticket_key)
        comment_row = _get_active_comment_row(
            session,
            actor,
            project,
            ticket.id,
            comment_id,
        )
        comment = comment_row[0]
        _require_expected_version(comment, payload.expected_version)
        _validate_comment_body(
            session,
            project.id,
            ticket.id,
            payload.body_document,
        )

        if comment.body_document != payload.body_document:
            before_version = comment.version
            comment.body_document = payload.body_document
            session.flush()
            record_comment_audit_event(
                session,
                "comment.updated",
                actor.id,
                comment,
                before_version=before_version,
                after_version=comment.version,
            )
            comment_changed = True
            comment_row = _get_active_comment_row(
                session,
                actor,
                project,
                ticket.id,
                comment.id,
            )
        result = build_comment_view(
            comment_row,
            depth=1 if comment.parent_comment_id is not None else 0,
        )

    if comment_changed:
        logger.info(
            "comment_updated comment_id=%s project_id=%s ticket_id=%s",
            result.id,
            result.project_id,
            result.ticket_id,
        )
    return result


def delete_comment(
    session: Session,
    actor: Identity,
    project_key: str,
    ticket_key: str,
    comment_id: int,
    payload: CommentDelete,
) -> None:
    """댓글 원문을 유지하며 삭제 주체와 시각을 기록해 soft delete한다."""
    with project_service.project_operation_context(
        session,
        actor,
        "comment_delete",
        write_operation=True,
        conflict_code="comment_conflict",
        conflict_message="댓글 삭제 상태가 변경되었습니다. 다시 확인하세요.",
        stale_code="comment_version_conflict",
        stale_message="다른 사용자가 먼저 댓글을 변경했습니다. 최신 내용을 다시 불러오세요.",
    ):
        project = project_service.require_project_user_access(session, actor, project_key)
        _require_active_project(project)
        ticket = _get_accessible_ticket(session, actor, project, ticket_key)
        comment_row = _get_active_comment_row(
            session,
            actor,
            project,
            ticket.id,
            comment_id,
        )
        comment = comment_row[0]
        _require_expected_version(comment, payload.expected_version)
        before_version = comment.version
        comment.deleted_at = utc_now()
        comment.deleted_by_id = actor.id
        session.flush()
        record_comment_audit_event(
            session,
            "comment.deleted",
            actor.id,
            comment,
            before_version=before_version,
            after_version=comment.version,
        )
        deleted_comment_id = comment.id
        deleted_project_id = comment.project_id
        deleted_ticket_id = comment.ticket_id

    logger.info(
        "comment_deleted comment_id=%s project_id=%s ticket_id=%s",
        deleted_comment_id,
        deleted_project_id,
        deleted_ticket_id,
    )
