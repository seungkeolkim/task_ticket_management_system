"""첨부파일 이름, MIME type과 실제 파일 형식 검증 규칙."""

from __future__ import annotations

import codecs
import re
import zipfile
from typing import BinaryIO

from app.core.config import AttachmentSettings

SAFE_PROJECT_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,31}$")
TEXT_EXTENSIONS = {"txt", "md", "csv"}
ZIP_EXTENSIONS = {"zip", "docx", "xlsx", "pptx"}
MAX_ARCHIVE_ENTRIES = 10_000
INLINE_IMAGE_MEDIA_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
    }
)


class AttachmentValidationError(ValueError):
    """사용자에게 노출할 수 있는 첨부파일 검증 실패를 표현한다."""

    def __init__(self, code: str, message: str) -> None:
        """안정적인 오류 code와 사용자 메시지를 저장한다."""
        self.code = code
        self.message = message
        super().__init__(message)


def normalize_attachment_filename(raw_filename: str | None) -> str:
    """업로드 경로를 제거하고 표시용 원본 파일명을 검증한다."""
    normalized_path = (raw_filename or "").replace("\\", "/")
    filename = normalized_path.rsplit("/", 1)[-1].strip()
    if not filename or filename in {".", ".."}:
        raise AttachmentValidationError("invalid_attachment_name", "파일명을 확인하세요.")
    if len(filename) > 512:
        raise AttachmentValidationError(
            "invalid_attachment_name",
            "파일명은 512자 이하로 입력하세요.",
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in filename):
        raise AttachmentValidationError(
            "invalid_attachment_name",
            "파일명에 제어문자를 사용할 수 없습니다.",
        )
    return filename


def attachment_extension(filename: str) -> str:
    """검증된 파일명에서 마지막 확장자를 소문자로 반환한다."""
    if "." not in filename or filename.endswith("."):
        raise AttachmentValidationError(
            "attachment_extension_required",
            "허용된 확장자가 있는 파일만 업로드할 수 있습니다.",
        )
    return filename.rsplit(".", 1)[-1].lower()


def validate_attachment_metadata(
    settings: AttachmentSettings,
    raw_filename: str | None,
    declared_media_type: str | None,
) -> tuple[str, str, str]:
    """파일명·확장자·요청 MIME type을 allowlist와 대조한다."""
    filename = normalize_attachment_filename(raw_filename)
    extension = attachment_extension(filename)
    if extension in settings.blocked_extensions:
        raise AttachmentValidationError(
            "blocked_attachment_extension",
            "실행 파일과 스크립트 파일은 업로드할 수 없습니다.",
        )
    if extension not in settings.allowed_extensions:
        raise AttachmentValidationError(
            "unsupported_attachment_extension",
            "허용되지 않은 파일 확장자입니다.",
        )

    media_type = (declared_media_type or "").split(";", 1)[0].strip().lower()
    if media_type not in settings.allowed_media_types.get(extension, []):
        raise AttachmentValidationError(
            "attachment_media_type_mismatch",
            "파일 확장자와 MIME type이 일치하지 않습니다.",
        )
    return filename, extension, media_type


def validate_attachment_content(file_handle: BinaryIO, extension: str) -> None:
    """확장자별 signature 또는 container 구조로 실제 파일 형식을 검증한다."""
    try:
        file_handle.seek(0)
        header = file_handle.read(16)
        file_handle.seek(0)
        if extension == "png" and not header.startswith(b"\x89PNG\r\n\x1a\n"):
            _raise_content_mismatch()
        elif extension in {"jpg", "jpeg"} and not header.startswith(b"\xff\xd8\xff"):
            _raise_content_mismatch()
        elif extension == "gif" and header[:6] not in {b"GIF87a", b"GIF89a"}:
            _raise_content_mismatch()
        elif extension == "webp" and not (
            header.startswith(b"RIFF") and header[8:12] == b"WEBP"
        ):
            _raise_content_mismatch()
        elif extension == "pdf" and not header.startswith(b"%PDF-"):
            _raise_content_mismatch()
        elif extension in TEXT_EXTENSIONS:
            _validate_utf8_text(file_handle)
        elif extension in ZIP_EXTENSIONS:
            _validate_zip_container(file_handle, extension)
    finally:
        file_handle.seek(0)


def is_inline_image_media_type(media_type: str) -> bool:
    """브라우저 본문에 안전하게 표시할 수 있는 raster image MIME type인지 반환한다."""
    return media_type in INLINE_IMAGE_MEDIA_TYPES


def build_attachment_storage_key(
    project_key: str,
    ticket_id: int,
    storage_identifier: str,
    extension: str,
) -> str:
    """프로젝트·티켓·hash shard가 드러나는 상대 저장 key를 생성한다."""
    if not SAFE_PROJECT_KEY_PATTERN.fullmatch(project_key) or ticket_id <= 0:
        raise ValueError("Invalid project or ticket identifier for attachment storage")
    if not re.fullmatch(r"[0-9a-f]{32}", storage_identifier):
        raise ValueError("Invalid attachment storage identifier")
    if not re.fullmatch(r"[a-z0-9]+", extension):
        raise ValueError("Invalid attachment extension")
    return "/".join(
        (
            "projects",
            project_key,
            "tickets",
            str(ticket_id),
            storage_identifier[:2],
            storage_identifier[2:4],
            f"{storage_identifier}.{extension}",
        )
    )


def _raise_content_mismatch() -> None:
    """실제 파일 형식 불일치 오류를 발생시킨다."""
    raise AttachmentValidationError(
        "attachment_content_mismatch",
        "파일 내용과 확장자가 일치하지 않습니다.",
    )


def _validate_utf8_text(file_handle: BinaryIO) -> None:
    """텍스트 첨부파일이 NUL 없는 UTF-8인지 stream 단위로 검증한다."""
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    try:
        while chunk := file_handle.read(64 * 1024):
            if b"\x00" in chunk:
                _raise_content_mismatch()
            decoder.decode(chunk)
        decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        _raise_content_mismatch()


def _validate_zip_container(file_handle: BinaryIO, extension: str) -> None:
    """ZIP 및 OOXML 첨부파일의 중앙 디렉터리와 필수 경로를 검증한다."""
    try:
        with zipfile.ZipFile(file_handle) as archive:
            names = archive.namelist()
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        _raise_content_mismatch()
        return

    if len(names) > MAX_ARCHIVE_ENTRIES:
        raise AttachmentValidationError(
            "attachment_archive_too_many_entries",
            "압축 파일의 항목 수가 너무 많습니다.",
        )
    if extension == "zip":
        return

    required_prefix_by_extension = {
        "docx": "word/",
        "xlsx": "xl/",
        "pptx": "ppt/",
    }
    required_prefix = required_prefix_by_extension[extension]
    if "[Content_Types].xml" not in names or not any(
        name.startswith(required_prefix) for name in names
    ):
        _raise_content_mismatch()
