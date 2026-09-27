"""댓글 생성·수정·조회에 사용하는 DTO."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.rich_text import validate_body_document


class CommentCreate(BaseModel):
    """댓글 생성 요청 본문을 검증한다."""

    model_config = ConfigDict(extra="forbid")

    body_document: dict[str, Any]
    parent_comment_id: int | None = Field(default=None, gt=0)

    @field_validator("body_document")
    @classmethod
    def validate_comment_document(cls, value: object) -> dict[str, Any]:
        """댓글 document를 body schema v2 계약으로 검증한다."""
        return validate_body_document(value)


class CommentUpdate(BaseModel):
    """댓글 수정 요청 본문과 optimistic lock version을 검증한다."""

    model_config = ConfigDict(extra="forbid")

    body_document: dict[str, Any]
    expected_version: int = Field(gt=0)

    @field_validator("body_document")
    @classmethod
    def validate_comment_document(cls, value: object) -> dict[str, Any]:
        """댓글 document를 body schema v2 계약으로 검증한다."""
        return validate_body_document(value)


class CommentDelete(BaseModel):
    """댓글 soft delete 요청의 optimistic lock version을 검증한다."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(gt=0)


class CommentAuthorView(BaseModel):
    """댓글 작성자에게 공개할 최소 사용자 정보를 표현한다."""

    id: int
    login_id: str
    display_name: str


class CommentView(BaseModel):
    """댓글 원문과 안전하게 렌더링된 파생 결과를 표현한다."""

    id: int
    project_id: int
    ticket_id: int
    parent_comment_id: int | None
    depth: Literal[0, 1]
    author: CommentAuthorView
    body_document: dict[str, Any]
    body_html: str
    body_plain_text: str
    body_schema_version: Literal[2]
    version: int
    is_deleted: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
