"""프로젝트·티켓 범위 첨부파일 repository query."""

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, aliased

from app.models import Attachment, Project, Ticket, User


def list_attachment_rows(session: Session, project_id: int, ticket_id: int):
    """티켓의 접근 가능한 일반 첨부파일을 최신순으로 조회한다."""
    uploader = aliased(User)
    return session.execute(
        select(
            Attachment,
            uploader.id.label("uploader_id"),
            uploader.login_id.label("uploader_login_id"),
            uploader.display_name.label("uploader_display_name"),
        )
        .join(uploader, uploader.id == Attachment.uploaded_by_id)
        .where(
            Attachment.project_id == project_id,
            Attachment.ticket_id == ticket_id,
            Attachment.comment_id.is_(None),
            Attachment.deleted_at.is_(None),
        )
        .order_by(Attachment.created_at.desc(), Attachment.id.desc())
    ).all()


def active_attachment_row(
    session: Session,
    project_id: int,
    ticket_id: int,
    attachment_id: int,
):
    """프로젝트·티켓 범위에서 삭제되지 않은 일반 첨부파일 한 건을 조회한다."""
    uploader = aliased(User)
    return session.execute(
        select(
            Attachment,
            uploader.id.label("uploader_id"),
            uploader.login_id.label("uploader_login_id"),
            uploader.display_name.label("uploader_display_name"),
        )
        .join(uploader, uploader.id == Attachment.uploaded_by_id)
        .where(
            Attachment.id == attachment_id,
            Attachment.project_id == project_id,
            Attachment.ticket_id == ticket_id,
            Attachment.comment_id.is_(None),
            Attachment.deleted_at.is_(None),
        )
    ).one_or_none()


def active_attachment_row_by_id(session: Session, attachment_id: int):
    """권한 확인 전 단계에서 활성 첨부파일과 소속 프로젝트·티켓 key를 조회한다."""
    uploader = aliased(User)
    return session.execute(
        select(
            Attachment,
            uploader.id.label("uploader_id"),
            uploader.login_id.label("uploader_login_id"),
            uploader.display_name.label("uploader_display_name"),
            Project.key.label("project_key"),
            Ticket.key.label("ticket_key"),
        )
        .join(uploader, uploader.id == Attachment.uploaded_by_id)
        .join(Project, Project.id == Attachment.project_id)
        .join(
            Ticket,
            and_(
                Ticket.project_id == Attachment.project_id,
                Ticket.id == Attachment.ticket_id,
                Ticket.deleted_at.is_(None),
            ),
        )
        .where(
            Attachment.id == attachment_id,
            Attachment.deleted_at.is_(None),
        )
    ).one_or_none()


def active_attachment_ids(session: Session, project_id: int, ticket_id: int) -> list[int]:
    """이력 기록용 활성 첨부파일 ID를 안정적인 순서로 반환한다."""
    return list(
        session.scalars(
            select(Attachment.id)
            .where(
                and_(
                    Attachment.project_id == project_id,
                    Attachment.ticket_id == ticket_id,
                    Attachment.comment_id.is_(None),
                    Attachment.deleted_at.is_(None),
                )
            )
            .order_by(Attachment.id)
        )
    )
