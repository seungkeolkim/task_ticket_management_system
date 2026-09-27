"""일반 첨부파일 API와 화면에 사용하는 DTO."""

from datetime import datetime

from pydantic import BaseModel


class AttachmentUploaderView(BaseModel):
    """첨부파일 업로더의 공개 가능한 최소 정보를 표현한다."""

    id: int
    login_id: str
    display_name: str


class AttachmentView(BaseModel):
    """저장소 내부 경로를 제외한 첨부파일 metadata를 표현한다."""

    id: int
    project_id: int
    ticket_id: int
    original_filename: str
    media_type: str
    size_bytes: int
    size_label: str
    uploader: AttachmentUploaderView
    created_at: datetime


class AttachmentUploadResult(BaseModel):
    """업로드 결과와 증가한 티켓 version을 반환한다."""

    attachment: AttachmentView
    ticket_version: int
