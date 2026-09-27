"""티켓 일반 첨부파일 JSON·binary API."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import Identity
from app.schemas.attachments import AttachmentUploadResult, AttachmentView
from app.services import attachments as service
from app.storage.attachments import AttachmentStorage, get_attachment_storage
from app.web.attachment_responses import build_attachment_download_response
from app.web.security import require_api_user, verify_csrf

router = APIRouter(
    prefix="/api/projects/{project_key}/tickets/{ticket_key}/attachments",
    tags=["attachments"],
)
Database = Annotated[Session, Depends(get_db_session)]
Actor = Annotated[Identity, Depends(require_api_user)]
Storage = Annotated[AttachmentStorage, Depends(get_attachment_storage)]


@router.get("", response_model=list[AttachmentView])
def list_ticket_attachments_api(
    project_key: str,
    ticket_key: str,
    session: Database,
    actor: Actor,
):
    """티켓의 삭제되지 않은 일반 첨부파일 목록을 조회한다."""
    return service.list_ticket_attachments(session, actor, project_key, ticket_key)[2]


@router.post("", response_model=AttachmentUploadResult, status_code=201)
def upload_ticket_attachment_api(
    project_key: str,
    ticket_key: str,
    request: Request,
    session: Database,
    actor: Actor,
    storage: Storage,
    file: Annotated[UploadFile, File()],
    expected_version: Annotated[int, Form(gt=0)],
):
    """multipart 일반 첨부파일을 검증하여 티켓에 등록한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.upload_ticket_attachment(
        session,
        actor,
        project_key,
        ticket_key,
        raw_filename=file.filename,
        declared_media_type=file.content_type,
        source=file.file,
        expected_version=expected_version,
        storage=storage,
    )


@router.get("/{attachment_id}/download")
def download_ticket_attachment_api(
    project_key: str,
    ticket_key: str,
    attachment_id: int,
    session: Database,
    actor: Actor,
    storage: Storage,
):
    """프로젝트 접근 권한을 확인한 뒤 첨부파일 blob을 전송한다."""
    download = service.open_ticket_attachment_download(
        session,
        actor,
        project_key,
        ticket_key,
        attachment_id,
        storage,
    )
    return build_attachment_download_response(download)
