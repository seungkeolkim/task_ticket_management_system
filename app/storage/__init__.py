"""외부 blob 저장소 adapter package."""

from app.storage.attachments import (
    AttachmentStorage,
    LocalAttachmentStorage,
    StagedAttachment,
    StoredAttachment,
    get_attachment_storage,
)

__all__ = [
    "AttachmentStorage",
    "LocalAttachmentStorage",
    "StagedAttachment",
    "StoredAttachment",
    "get_attachment_storage",
]
