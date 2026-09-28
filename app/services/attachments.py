"""일반 티켓 첨부파일 조회·업로드·다운로드 application service."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.types import utc_now
from app.domain.attachments import (
    AttachmentValidationError,
    build_attachment_storage_key,
    is_inline_image_media_type,
    validate_attachment_content,
    validate_attachment_metadata,
)
from app.domain.auth import AuthError, Identity
from app.domain.codes import ProjectRole
from app.models import Attachment, AuditLog
from app.repositories import attachments as repository
from app.repositories import tickets as ticket_repository
from app.schemas.attachments import (
    AttachmentUploaderView,
    AttachmentUploadResult,
    AttachmentView,
)
from app.services import projects as project_service
from app.services import tickets as ticket_service
from app.storage.attachments import (
    AttachmentBlobNotFoundError,
    AttachmentSizeExceededError,
    AttachmentStorage,
    AttachmentStorageError,
    StagedAttachment,
)

logger = logging.getLogger(__name__)
DOWNLOAD_CHUNK_SIZE = 64 * 1024


@dataclass
class AttachmentDownload:
    """다운로드 응답에 필요한 metadata와 열린 blob stream을 묶는다."""

    attachment: AttachmentView
    file_handle: BinaryIO


def can_manage_attachments(project) -> bool:
    """현재 프로젝트에서 일반 첨부파일을 업로드할 수 있는지 반환한다."""
    return project.is_active and (
        project.role in {ProjectRole.ADMIN, ProjectRole.USER} or project.can_manage
    )


def build_attachment_view(attachment_row) -> AttachmentView:
    """첨부파일 ORM row를 내부 저장 key가 없는 공개 view로 변환한다."""
    attachment = attachment_row[0]
    mapping = attachment_row._mapping
    return AttachmentView(
        id=attachment.id,
        project_id=attachment.project_id,
        ticket_id=attachment.ticket_id,
        original_filename=attachment.original_filename,
        media_type=attachment.media_type,
        size_bytes=attachment.size_bytes,
        size_label=format_attachment_size(attachment.size_bytes),
        uploader=AttachmentUploaderView(
            id=mapping["uploader_id"],
            login_id=mapping["uploader_login_id"],
            display_name=mapping["uploader_display_name"],
        ),
        created_at=attachment.created_at,
    )


def format_attachment_size(size_bytes: int) -> str:
    """첨부파일 byte 크기를 화면용 단위로 변환한다."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def list_ticket_attachments(
    session: Session,
    actor: Identity,
    project_key: str,
    ticket_key: str,
):
    """권한 범위에서 티켓의 삭제되지 않은 일반 첨부파일을 조회한다."""
    with project_service.project_operation_context(session, actor, "attachment_list"):
        project = project_service.require_project_member(session, actor, project_key)
        ticket = _get_accessible_ticket(session, actor, project, ticket_key)
        attachment_rows = repository.list_attachment_rows(session, project.id, ticket.id)
        return project, ticket, [build_attachment_view(row) for row in attachment_rows]


def upload_ticket_attachment(
    session: Session,
    actor: Identity,
    project_key: str,
    ticket_key: str,
    *,
    raw_filename: str | None,
    declared_media_type: str | None,
    source: BinaryIO,
    expected_version: int,
    storage: AttachmentStorage,
) -> AttachmentUploadResult:
    """파일을 검증·staging한 뒤 metadata와 blob을 하나의 업무 변경으로 저장한다."""
    attachment_settings = get_settings().attachments
    try:
        filename, extension, media_type = validate_attachment_metadata(
            attachment_settings,
            raw_filename,
            declared_media_type,
        )
    except AttachmentValidationError as error:
        raise AuthError(error.code, error.message, 422) from error

    maximum_size_bytes = attachment_settings.max_file_size_mb * 1024 * 1024
    try:
        staged_attachment = storage.stage(source, maximum_size_bytes)
    except AttachmentSizeExceededError as error:
        raise AuthError(
            "attachment_too_large",
            f"첨부파일은 {attachment_settings.max_file_size_mb}MB 이하만 업로드할 수 있습니다.",
            413,
        ) from error
    except Exception as error:
        logger.exception("attachment_stage_failed actor_id=%s", actor.id)
        raise AuthError(
            "attachment_storage_failed",
            "첨부파일을 임시 저장하지 못했습니다.",
            500,
        ) from error

    if staged_attachment.size_bytes == 0:
        storage.discard_staged(staged_attachment)
        raise AuthError("empty_attachment", "빈 파일은 업로드할 수 없습니다.", 422)

    try:
        with storage.open_staged(staged_attachment) as staged_file:
            validate_attachment_content(staged_file, extension)
    except AttachmentValidationError as error:
        storage.discard_staged(staged_attachment)
        raise AuthError(error.code, error.message, 422) from error
    except Exception as error:
        storage.discard_staged(staged_attachment)
        logger.exception("attachment_validation_failed actor_id=%s", actor.id)
        raise AuthError(
            "attachment_storage_failed",
            "첨부파일을 검증하지 못했습니다.",
            500,
        ) from error

    committed_storage_key: str | None = None
    try:
        with project_service.project_operation_context(
            session,
            actor,
            "attachment_upload",
            write_operation=True,
            conflict_code="attachment_conflict",
            conflict_message="첨부파일 등록 상태가 변경되었습니다. 다시 확인하세요.",
            stale_code="ticket_version_conflict",
            stale_message="다른 사용자가 먼저 티켓을 변경했습니다. 최신 내용을 다시 불러오세요.",
        ):
            project = project_service.require_project_user_access(session, actor, project_key)
            _require_active_project(project)
            ticket = _get_accessible_ticket(session, actor, project, ticket_key)
            _require_expected_version(ticket.version, expected_version)

            parent_key = ticket_repository.parent_key_for_ticket(
                session,
                project.id,
                ticket,
            )
            before_attachment_ids = repository.active_attachment_ids(
                session,
                project.id,
                ticket.id,
            )
            before_snapshot = ticket_service.build_ticket_snapshot(
                session,
                ticket,
                parent_key,
            )

            storage_identifier = uuid4().hex
            storage_key = build_attachment_storage_key(
                project.key,
                ticket.id,
                storage_identifier,
                extension,
            )
            try:
                stored_attachment = storage.commit(staged_attachment, storage_key)
            except AttachmentStorageError as error:
                logger.exception(
                    "attachment_commit_failed actor_id=%s project_id=%s ticket_id=%s",
                    actor.id,
                    project.id,
                    ticket.id,
                )
                raise AuthError(
                    "attachment_storage_failed",
                    "첨부파일을 저장하지 못했습니다.",
                    500,
                ) from error
            committed_storage_key = stored_attachment.storage_key

            attachment = Attachment(
                project_id=project.id,
                ticket_id=ticket.id,
                comment_id=None,
                original_filename=filename,
                media_type=media_type,
                size_bytes=stored_attachment.size_bytes,
                storage_backend=storage.backend_name,
                storage_key=stored_attachment.storage_key,
                sha256=stored_attachment.sha256,
                uploaded_by_id=actor.id,
            )
            session.add(attachment)
            session.flush()

            ticket.updated_at = utc_now()
            session.flush()
            after_attachment_ids = [*before_attachment_ids, attachment.id]
            after_snapshot = ticket_service.build_ticket_snapshot(
                session,
                ticket,
                parent_key,
            )
            session.add(
                ticket_service.build_ticket_external_content_history(
                    ticket,
                    actor.id,
                    before_snapshot,
                    after_snapshot,
                    field="attachments",
                    before_value=before_attachment_ids,
                    after_value=after_attachment_ids,
                )
            )
            _record_attachment_audit_event(session, actor.id, attachment, ticket.version)
            attachment_row = repository.active_attachment_row(
                session,
                project.id,
                ticket.id,
                attachment.id,
            )
            result = AttachmentUploadResult(
                attachment=build_attachment_view(attachment_row),
                ticket_version=ticket.version,
            )
    except Exception:
        _rollback_stored_blob(storage, staged_attachment, committed_storage_key)
        raise

    logger.info(
        "attachment_uploaded attachment_id=%s project_id=%s ticket_id=%s size_bytes=%s",
        result.attachment.id,
        result.attachment.project_id,
        result.attachment.ticket_id,
        result.attachment.size_bytes,
    )
    return result


def open_ticket_attachment_download(
    session: Session,
    actor: Identity,
    project_key: str,
    ticket_key: str,
    attachment_id: int,
    storage: AttachmentStorage,
) -> AttachmentDownload:
    """프로젝트 접근 권한을 확인하고 다운로드용 blob stream을 연다."""
    with project_service.project_operation_context(session, actor, "attachment_download"):
        project = project_service.require_project_member(session, actor, project_key)
        ticket = _get_accessible_ticket(session, actor, project, ticket_key)
        attachment_row = repository.active_attachment_row(
            session,
            project.id,
            ticket.id,
            attachment_id,
        )
        if attachment_row is None:
            raise AuthError("attachment_not_found", "첨부파일을 찾을 수 없습니다.", 404)
        attachment = attachment_row[0]
        attachment_view = build_attachment_view(attachment_row)
        try:
            file_handle = storage.open(attachment.storage_key)
        except AttachmentBlobNotFoundError as error:
            logger.error(
                "attachment_blob_missing attachment_id=%s project_id=%s ticket_id=%s",
                attachment.id,
                attachment.project_id,
                attachment.ticket_id,
            )
            raise AuthError("attachment_not_found", "첨부파일을 찾을 수 없습니다.", 404) from error
    return AttachmentDownload(attachment=attachment_view, file_handle=file_handle)


def open_inline_attachment_image(
    session: Session,
    actor: Identity,
    attachment_id: int,
    storage: AttachmentStorage,
) -> AttachmentDownload:
    """활성 raster image의 프로젝트·티켓 권한을 확인하고 inline stream을 연다."""
    with project_service.project_operation_context(session, actor, "attachment_image_read"):
        attachment_row = repository.active_attachment_row_by_id(session, attachment_id)
        if attachment_row is None:
            raise AuthError("attachment_not_found", "첨부파일을 찾을 수 없습니다.", 404)

        attachment = attachment_row[0]
        mapping = attachment_row._mapping
        if not is_inline_image_media_type(attachment.media_type):
            raise AuthError("attachment_not_found", "첨부파일을 찾을 수 없습니다.", 404)

        project = project_service.require_project_member(
            session,
            actor,
            mapping["project_key"],
        )
        ticket = _get_accessible_ticket(
            session,
            actor,
            project,
            mapping["ticket_key"],
        )
        if ticket.id != attachment.ticket_id or storage.backend_name != attachment.storage_backend:
            raise AuthError("attachment_not_found", "첨부파일을 찾을 수 없습니다.", 404)

        attachment_view = build_attachment_view(attachment_row)
        try:
            file_handle = storage.open(attachment.storage_key)
        except AttachmentBlobNotFoundError as error:
            logger.error(
                "attachment_blob_missing attachment_id=%s project_id=%s ticket_id=%s",
                attachment.id,
                attachment.project_id,
                attachment.ticket_id,
            )
            raise AuthError("attachment_not_found", "첨부파일을 찾을 수 없습니다.", 404) from error
    return AttachmentDownload(attachment=attachment_view, file_handle=file_handle)


def iter_attachment_download(file_handle: BinaryIO) -> Iterator[bytes]:
    """응답 완료나 중단 시 file handle을 닫으며 blob을 chunk 단위로 반환한다."""
    try:
        while chunk := file_handle.read(DOWNLOAD_CHUNK_SIZE):
            yield chunk
    finally:
        file_handle.close()


def _get_accessible_ticket(session: Session, actor: Identity, project, ticket_key: str):
    """프로젝트 권한 범위에서 삭제되지 않은 티켓을 조회한다."""
    ticket_row = ticket_repository.ticket_row(
        session,
        project.id,
        actor.id,
        ticket_key.strip().upper(),
        override=ticket_service.uses_system_administrator_override(project),
    )
    if ticket_row is None:
        raise AuthError("ticket_not_found", "티켓을 찾을 수 없습니다.", 404)
    return ticket_row[0]


def _require_active_project(project) -> None:
    """비활성 프로젝트의 첨부파일 업로드를 거부한다."""
    if not project.is_active:
        raise AuthError(
            "project_inactive",
            "비활성 프로젝트에는 첨부파일을 등록할 수 없습니다.",
            409,
        )


def _require_expected_version(current_version: int, expected_version: int) -> None:
    """첨부파일 등록 전 티켓 optimistic lock version을 검증한다."""
    if current_version != expected_version:
        raise AuthError(
            "ticket_version_conflict",
            "다른 사용자가 먼저 티켓을 변경했습니다. 최신 내용을 다시 불러오세요.",
            409,
        )


def _record_attachment_audit_event(
    session: Session,
    actor_id: int,
    attachment: Attachment,
    ticket_version: int,
) -> None:
    """파일 본문과 내부 storage key를 제외한 첨부파일 생성 감사를 기록한다."""
    session.add(
        AuditLog(
            action="attachment.created",
            actor_user_id=actor_id,
            target_type="attachment",
            target_id=str(attachment.id),
            details={
                "project_id": attachment.project_id,
                "ticket_id": attachment.ticket_id,
                "attachment_id": attachment.id,
                "media_type": attachment.media_type,
                "size_bytes": attachment.size_bytes,
                "ticket_version": ticket_version,
            },
        )
    )


def _rollback_stored_blob(
    storage: AttachmentStorage,
    staged_attachment: StagedAttachment,
    committed_storage_key: str | None,
) -> None:
    """DB 실패 시 staging 또는 최종 blob을 보상 삭제한다."""
    try:
        if committed_storage_key is not None:
            storage.delete(committed_storage_key)
        else:
            storage.discard_staged(staged_attachment)
    except Exception:
        rollback_target = "committed" if committed_storage_key is not None else "staged"
        logger.exception("attachment_blob_rollback_failed target=%s", rollback_target)
