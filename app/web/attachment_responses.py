"""첨부파일 다운로드 응답 공통 구성."""

from urllib.parse import quote

from fastapi.responses import StreamingResponse

from app.services.attachments import AttachmentDownload, iter_attachment_download


def build_attachment_download_response(download: AttachmentDownload) -> StreamingResponse:
    """UTF-8 파일명과 정확한 길이를 포함한 protected 다운로드 응답을 생성한다."""
    encoded_filename = quote(download.attachment.original_filename, safe="")
    return StreamingResponse(
        iter_attachment_download(download.file_handle),
        media_type=download.attachment.media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "Content-Length": str(download.attachment.size_bytes),
        },
    )


def build_attachment_inline_response(download: AttachmentDownload) -> StreamingResponse:
    """권한이 확인된 image를 본문 표시용 inline 응답으로 생성한다."""
    encoded_filename = quote(download.attachment.original_filename, safe="")
    return StreamingResponse(
        iter_attachment_download(download.file_handle),
        media_type=download.attachment.media_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}",
            "Content-Length": str(download.attachment.size_bytes),
        },
    )
