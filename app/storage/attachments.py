"""첨부파일 blob 저장소 interface와 local mount adapter."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import BinaryIO, Protocol
from uuid import uuid4

from app.core.config import get_settings

COPY_CHUNK_SIZE = 64 * 1024


class AttachmentStorageError(RuntimeError):
    """첨부파일 저장소 작업 실패의 기반 예외."""


class AttachmentSizeExceededError(AttachmentStorageError):
    """업로드 stream이 설정된 최대 크기를 넘었음을 표현한다."""


class AttachmentBlobNotFoundError(AttachmentStorageError):
    """DB metadata가 가리키는 blob을 찾지 못했음을 표현한다."""


@dataclass(frozen=True)
class StagedAttachment:
    """검증 전 임시 blob의 저장소 식별자와 digest를 보관한다."""

    staging_key: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class StoredAttachment:
    """최종 저장된 blob의 상대 key와 digest를 보관한다."""

    storage_key: str
    size_bytes: int
    sha256: str


class AttachmentStorage(Protocol):
    """첨부파일 임시 저장·확정·조회에 필요한 저장소 계약."""

    backend_name: str

    def stage(self, source: BinaryIO, maximum_size_bytes: int) -> StagedAttachment:
        """업로드 stream을 크기 제한 안에서 임시 저장한다."""
        ...

    def open_staged(self, staged_attachment: StagedAttachment) -> BinaryIO:
        """검증을 위해 임시 blob을 연다."""
        ...

    def commit(
        self,
        staged_attachment: StagedAttachment,
        storage_key: str,
    ) -> StoredAttachment:
        """임시 blob을 최종 storage key로 원자적으로 이동한다."""
        ...

    def discard_staged(self, staged_attachment: StagedAttachment) -> None:
        """남아 있는 임시 blob을 제거한다."""
        ...

    def open(self, storage_key: str) -> BinaryIO:
        """다운로드할 최종 blob을 연다."""
        ...

    def delete(self, storage_key: str) -> None:
        """최종 blob을 제거한다."""
        ...


class LocalAttachmentStorage:
    """mount directory에 첨부파일을 저장하는 local adapter."""

    backend_name = "local"

    def __init__(self, root_directory: str) -> None:
        """절대화한 저장 root와 staging directory를 준비한다."""
        self.root_directory = os.path.realpath(os.path.abspath(root_directory))
        self.staging_directory = os.path.join(self.root_directory, ".staging")
        os.makedirs(self.staging_directory, exist_ok=True)

    def stage(self, source: BinaryIO, maximum_size_bytes: int) -> StagedAttachment:
        """upload stream을 임시 파일에 기록하며 크기와 SHA-256을 계산한다."""
        staging_identifier = uuid4().hex
        staging_key = f".staging/{staging_identifier}.upload"
        staging_path = self._resolve_storage_key(staging_key)
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            source.seek(0)
            with open(staging_path, "xb") as staged_file:
                while chunk := source.read(COPY_CHUNK_SIZE):
                    size_bytes += len(chunk)
                    if size_bytes > maximum_size_bytes:
                        raise AttachmentSizeExceededError(
                            "Attachment exceeds configured size limit"
                        )
                    digest.update(chunk)
                    staged_file.write(chunk)
            source.seek(0)
            return StagedAttachment(
                staging_key=staging_key,
                size_bytes=size_bytes,
                sha256=digest.hexdigest(),
            )
        except Exception:
            self._remove_file_if_present(staging_path)
            raise

    def open_staged(self, staged_attachment: StagedAttachment) -> BinaryIO:
        """검증을 위해 staging 영역의 blob을 binary mode로 연다."""
        staging_path = self._resolve_staging_key(staged_attachment.staging_key)
        try:
            return open(staging_path, "rb")
        except FileNotFoundError as error:
            raise AttachmentBlobNotFoundError("Staged attachment blob is missing") from error

    def commit(
        self,
        staged_attachment: StagedAttachment,
        storage_key: str,
    ) -> StoredAttachment:
        """staging blob을 shard가 포함된 최종 상대 경로로 이동한다."""
        staging_path = self._resolve_staging_key(staged_attachment.staging_key)
        final_path = self._resolve_storage_key(storage_key)
        os.makedirs(os.path.dirname(final_path), exist_ok=True)
        if os.path.exists(final_path):
            raise AttachmentStorageError("Attachment storage key already exists")
        try:
            os.replace(staging_path, final_path)
        except FileNotFoundError as error:
            raise AttachmentBlobNotFoundError("Staged attachment blob is missing") from error
        except OSError as error:
            raise AttachmentStorageError("Failed to commit attachment blob") from error
        return StoredAttachment(
            storage_key=storage_key,
            size_bytes=staged_attachment.size_bytes,
            sha256=staged_attachment.sha256,
        )

    def discard_staged(self, staged_attachment: StagedAttachment) -> None:
        """검증 실패나 요청 실패 후 staging blob을 멱등적으로 제거한다."""
        staging_path = self._resolve_staging_key(staged_attachment.staging_key)
        self._remove_file_if_present(staging_path)

    def open(self, storage_key: str) -> BinaryIO:
        """최종 blob을 binary mode로 연다."""
        file_path = self._resolve_storage_key(storage_key)
        try:
            return open(file_path, "rb")
        except FileNotFoundError as error:
            raise AttachmentBlobNotFoundError("Attachment blob is missing") from error
        except OSError as error:
            raise AttachmentStorageError("Failed to open attachment blob") from error

    def delete(self, storage_key: str) -> None:
        """rollback 또는 영구 정리를 위해 최종 blob을 멱등적으로 제거한다."""
        file_path = self._resolve_storage_key(storage_key)
        self._remove_file_if_present(file_path)

    def _resolve_staging_key(self, staging_key: str) -> str:
        """staging key가 전용 directory 바로 아래인지 검증한다."""
        resolved_path = self._resolve_storage_key(staging_key)
        if os.path.dirname(resolved_path) != self.staging_directory:
            raise AttachmentStorageError("Invalid attachment staging key")
        return resolved_path

    def _resolve_storage_key(self, storage_key: str) -> str:
        """상대 storage key를 root 밖으로 벗어나지 않는 절대 경로로 변환한다."""
        normalized_key = storage_key.replace("\\", "/")
        path_parts = normalized_key.split("/")
        if (
            not normalized_key
            or normalized_key.startswith("/")
            or any(part in {"", ".", ".."} for part in path_parts)
        ):
            raise AttachmentStorageError("Invalid attachment storage key")
        resolved_path = os.path.realpath(os.path.join(self.root_directory, *path_parts))
        if os.path.commonpath((self.root_directory, resolved_path)) != self.root_directory:
            raise AttachmentStorageError("Attachment storage key escapes the configured root")
        return resolved_path

    @staticmethod
    def _remove_file_if_present(file_path: str) -> None:
        """대상 파일이 있으면 제거하고 이미 없으면 성공으로 처리한다."""
        try:
            os.remove(file_path)
        except FileNotFoundError:
            return


@lru_cache(maxsize=1)
def get_attachment_storage() -> AttachmentStorage:
    """현재 설정에 맞는 첨부파일 저장소 adapter를 반환한다."""
    return LocalAttachmentStorage(get_settings().attachments_directory)
