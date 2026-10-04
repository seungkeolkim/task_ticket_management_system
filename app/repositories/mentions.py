"""프로젝트 구성원과 본인 멘션의 접근 범위를 제한하는 query."""

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import Comment, Mention, ProjectMember, Ticket, User


def eligible_users(session: Session, project_id: int, *, user_ids=None, query=""):
    """활성 프로젝트 구성원을 검색하거나 지정된 ID 집합을 검증한다."""
    statement = (
        select(User)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project_id, User.is_active.is_(True))
    )
    if user_ids is not None:
        statement = statement.where(User.id.in_(user_ids))
    else:
        if query:
            statement = statement.where(
                or_(
                    User.login_id.contains(query, autoescape=True),
                    User.display_name.contains(query, autoescape=True),
                )
            )
        statement = statement.limit(50)
    return session.scalars(statement.order_by(User.display_name, User.id)).all()


def source_mentions(session: Session, ticket_id: int, comment_id: int | None):
    """본문 원본별 멘션을 제거된 항목까지 조회한다."""
    return session.scalars(
        select(Mention).where(Mention.ticket_id == ticket_id, Mention.comment_id == comment_id)
    ).all()


def accessible_inbox(actor_id: int):
    """본인의 현재 membership과 삭제되지 않은 원본을 query에서 강제한다."""
    return (
        select(Mention)
        .join(
            ProjectMember,
            and_(
                ProjectMember.project_id == Mention.project_id,
                ProjectMember.user_id == actor_id,
            ),
        )
        .join(Ticket, Ticket.id == Mention.ticket_id)
        .outerjoin(Comment, Comment.id == Mention.comment_id)
        .where(
            Mention.target_user_id == actor_id,
            Mention.removed_at.is_(None),
            Ticket.deleted_at.is_(None),
            or_(Mention.comment_id.is_(None), Comment.deleted_at.is_(None)),
        )
    )


def inbox_mentions(session: Session, actor_id: int, mention_id: int | None):
    """단일 멘션 또는 현재 읽을 수 있는 미확인 멘션 전체를 조회한다."""
    statement = accessible_inbox(actor_id)
    if mention_id is None:
        statement = statement.where(Mention.read_at.is_(None))
    else:
        statement = statement.where(Mention.id == mention_id)
    return session.scalars(statement).all()
