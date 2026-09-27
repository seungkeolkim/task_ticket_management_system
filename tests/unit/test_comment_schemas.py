import pytest
from pydantic import ValidationError

from app.schemas.comments import CommentCreate, CommentDelete, CommentUpdate


def valid_document() -> dict[str, object]:
    """댓글 DTO 테스트에 사용할 유효한 document를 반환한다."""
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "댓글"}],
            }
        ],
    }


def test_comment_schema_normalizes_document_and_rejects_extra_fields():
    """댓글 DTO가 body schema를 정규화하고 알 수 없는 필드를 거부하는지 검증한다."""
    payload = CommentCreate(body_document={"type": "doc", "content": []})
    assert payload.body_document == {"type": "doc", "content": [{"type": "paragraph"}]}
    with pytest.raises(ValidationError):
        CommentCreate(body_document=valid_document(), unexpected=True)


def test_comment_create_requires_positive_parent_comment_id():
    """대댓글 부모 ID를 생략하거나 양수로만 지정할 수 있는지 검증한다."""
    root_payload = CommentCreate(body_document=valid_document())
    reply_payload = CommentCreate(body_document=valid_document(), parent_comment_id=12)
    assert root_payload.parent_comment_id is None
    assert reply_payload.parent_comment_id == 12
    with pytest.raises(ValidationError):
        CommentCreate(body_document=valid_document(), parent_comment_id=0)


def test_comment_update_and_delete_require_positive_version():
    """댓글 수정·삭제 DTO가 양의 expected_version을 요구하는지 검증한다."""
    with pytest.raises(ValidationError):
        CommentUpdate(body_document=valid_document(), expected_version=0)
    with pytest.raises(ValidationError):
        CommentDelete(expected_version=0)
