"""프로젝트 권한 범위가 적용된 댓글 저장소 query."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Attachment, Comment, Project, ProjectMember, User


def _accessible_project_ids(actor_id: int, *, override: bool):
    """댓글 query에 재사용할 접근 가능한 프로젝트 ID 범위를 구성한다."""
    query = (
        select(Project.id)
        .outerjoin(
            ProjectMember,
            (ProjectMember.project_id == Project.id) & (ProjectMember.user_id == actor_id),
        )
    )
    if not override:
        query = query.where(ProjectMember.user_id == actor_id)
    return query


def _comment_select(actor_id: int, *, override: bool):
    """작성자 정보와 프로젝트 membership 조건을 포함한 댓글 select를 구성한다."""
    accessible_project_ids = _accessible_project_ids(actor_id, override=override).subquery()
    return (
        select(
            Comment,
            User.id.label("author_id"),
            User.login_id.label("author_login_id"),
            User.display_name.label("author_display_name"),
        )
        .join(User, User.id == Comment.author_id)
        .where(Comment.project_id.in_(select(accessible_project_ids.c.id)))
    )


def list_active_comment_rows(
    session: Session,
    project_id: int,
    ticket_id: int,
    actor_id: int,
    *,
    override: bool,
):
    """티켓의 삭제되지 않은 댓글과 작성자를 안정적인 순서로 조회한다."""
    return session.execute(
        _comment_select(actor_id, override=override)
        .where(
            Comment.project_id == project_id,
            Comment.ticket_id == ticket_id,
            Comment.deleted_at.is_(None),
        )
        .order_by(Comment.created_at, Comment.id)
    ).all()


def active_comment_row(
    session: Session,
    project_id: int,
    ticket_id: int,
    comment_id: int,
    actor_id: int,
    *,
    override: bool,
):
    """프로젝트·티켓 scope 안의 삭제되지 않은 단일 댓글을 조회한다."""
    return session.execute(
        _comment_select(actor_id, override=override).where(
            Comment.project_id == project_id,
            Comment.ticket_id == ticket_id,
            Comment.id == comment_id,
            Comment.deleted_at.is_(None),
        )
    ).one_or_none()


def available_ticket_attachment_ids(
    session: Session,
    project_id: int,
    ticket_id: int,
    attachment_ids: set[int],
) -> set[int]:
    """같은 프로젝트·티켓에서 현재 참조 가능한 attachment ID를 반환한다."""
    if not attachment_ids:
        return set()
    return set(
        session.scalars(
            select(Attachment.id).where(
                Attachment.project_id == project_id,
                Attachment.ticket_id == ticket_id,
                Attachment.id.in_(attachment_ids),
                Attachment.deleted_at.is_(None),
            )
        )
    )
