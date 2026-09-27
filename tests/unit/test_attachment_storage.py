from io import BytesIO
from pathlib import Path

import pytest

from app.domain.attachments import (
    AttachmentValidationError,
    build_attachment_storage_key,
    validate_attachment_content,
)
from app.storage.attachments import AttachmentStorageError, LocalAttachmentStorage


class FailingUploadStream(BytesIO):
    """첫 chunk 이후 filesystem source read 실패를 재현한다."""

    def __init__(self, initial_bytes: bytes) -> None:
        """첫 read에 반환할 bytes를 저장한다."""
        super().__init__(initial_bytes)
        self.read_count = 0

    def read(self, size: int = -1) -> bytes:
        """첫 read 이후 의도한 I/O 오류를 발생시킨다."""
        self.read_count += 1
        if self.read_count > 1:
            raise OSError("forced upload read failure")
        return super().read(size)


def test_storage_key_uses_project_ticket_and_hash_shards() -> None:
    """storage key가 프로젝트·티켓과 두 단계 hash shard를 포함하는지 검증한다."""
    identifier = "0123456789abcdef0123456789abcdef"

    storage_key = build_attachment_storage_key("DEV", 42, identifier, "pdf")

    assert storage_key == (
        "projects/DEV/tickets/42/01/23/0123456789abcdef0123456789abcdef.pdf"
    )


def test_local_storage_stages_and_commits_inside_root(tmp_path: Path) -> None:
    """local adapter가 staging blob을 최종 shard 경로로 원자 이동하는지 검증한다."""
    storage = LocalAttachmentStorage(str(tmp_path))
    content = b"%PDF-1.4\nlocal attachment"
    staged_attachment = storage.stage(BytesIO(content), maximum_size_bytes=1024)
    storage_key = build_attachment_storage_key(
        "DEV",
        9,
        "abcdef0123456789abcdef0123456789",
        "pdf",
    )

    stored_attachment = storage.commit(staged_attachment, storage_key)

    assert stored_attachment.size_bytes == len(content)
    with storage.open(storage_key) as file_handle:
        assert file_handle.read() == content
    assert not any((tmp_path / ".staging").iterdir())


def test_local_storage_rejects_path_traversal(tmp_path: Path) -> None:
    """상대 storage key가 설정 root 밖으로 탈출하지 못하는지 검증한다."""
    storage = LocalAttachmentStorage(str(tmp_path))

    with pytest.raises(AttachmentStorageError):
        storage.open("../outside.txt")


def test_local_storage_removes_partial_staging_file_after_stream_failure(
    tmp_path: Path,
) -> None:
    """upload stream I/O 실패가 부분 staging 파일을 남기지 않는지 검증한다."""
    storage = LocalAttachmentStorage(str(tmp_path))
    failing_stream = FailingUploadStream(b"partial upload")

    with pytest.raises(OSError, match="forced upload read failure"):
        storage.stage(failing_stream, maximum_size_bytes=1024)

    assert not any((tmp_path / ".staging").iterdir())


def test_pdf_extension_rejects_non_pdf_content() -> None:
    """요청 MIME type과 별개로 실제 signature가 다른 파일을 거부하는지 검증한다."""
    with pytest.raises(AttachmentValidationError) as error:
        validate_attachment_content(BytesIO(b"not a pdf"), "pdf")

    assert error.value.code == "attachment_content_mismatch"


def test_ooxml_extension_requires_matching_container_directory() -> None:
    """일반 ZIP을 DOCX로 위장한 파일을 거부하는지 검증한다."""
    import zipfile

    archive_bytes = BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("xl/workbook.xml", "sheet")
    archive_bytes.seek(0)

    with pytest.raises(AttachmentValidationError):
        validate_attachment_content(archive_bytes, "docx")
