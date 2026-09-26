from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.codes import Priority, RelationType, TicketStatus, TicketType
from app.domain.rich_text import empty_body_document, validate_body_document


class TicketCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: TicketType = TicketType.TASK
    title: str = Field(min_length=1, max_length=200)
    description_document: dict[str, Any] = Field(default_factory=empty_body_document)
    priority: Priority = Priority.MAJOR
    parent_key: str | None = Field(default=None, max_length=64)
    assignee_id: int | None = Field(default=None, gt=0)
    due_date: date | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        """title 값을 정규화한다."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("제목을 입력하세요.")
        return normalized

    @field_validator("description_document")
    @classmethod
    def validate_description_document(cls, value: object) -> dict[str, Any]:
        """티켓 설명 document를 body schema v2 계약으로 검증한다."""
        return validate_body_document(value)

    @field_validator("parent_key", mode="before")
    @classmethod
    def normalize_parent_key(cls, value: object) -> object:
        """상위 항목 key 값을 정규화한다."""
        if value is None:
            return None
        normalized = str(value).strip().upper()
        return normalized or None

    @model_validator(mode="after")
    def validate_parent_shape(self):
        """상위 항목 shape 값을 검증한다."""
        if self.type == TicketType.EPIC and self.parent_key is not None:
            raise ValueError("Epic은 상위 티켓을 가질 수 없습니다.")
        if self.type == TicketType.SUBTASK and self.parent_key is None:
            raise ValueError("Subtask는 상위 Task가 필요합니다.")
        return self


class TicketUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description_document: dict[str, Any] = Field(default_factory=empty_body_document)
    priority: Priority
    parent_key: str | None = Field(default=None, max_length=64)
    assignee_id: int | None = Field(default=None, gt=0)
    due_date: date | None = None
    expected_version: int = Field(gt=0)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        """title 값을 정규화한다."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("제목을 입력하세요.")
        return normalized

    @field_validator("description_document")
    @classmethod
    def validate_description_document(cls, value: object) -> dict[str, Any]:
        """티켓 설명 document를 body schema v2 계약으로 검증한다."""
        return validate_body_document(value)

    @field_validator("parent_key", mode="before")
    @classmethod
    def normalize_parent_key(cls, value: object) -> object:
        """상위 항목 key 값을 정규화한다."""
        if value is None:
            return None
        normalized = str(value).strip().upper()
        return normalized or None


class TicketTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_status: TicketStatus
    expected_version: int = Field(gt=0)
    confirm_incomplete_children: bool = False


class TicketRelationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relation_type: RelationType
    target_ticket_key: str = Field(min_length=1, max_length=64)
    expected_version: int = Field(gt=0)

    @field_validator("target_ticket_key")
    @classmethod
    def normalize_target_ticket_key(cls, value: str) -> str:
        """관계 대상 티켓 key를 정규화한다."""
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("관계 대상 티켓을 입력하세요.")
        return normalized


class TicketRelationDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(gt=0)


class TicketTrashMove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(gt=0)


class TicketTrashRestore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(gt=0)


class TicketUserView(BaseModel):
    id: int
    login_id: str
    display_name: str


class TicketParentView(BaseModel):
    key: str
    type: TicketType
    title: str


class TicketView(BaseModel):
    id: int
    project_id: int
    project_key: str
    project_name: str
    number: int
    key: str
    type: TicketType
    type_label: str
    title: str
    description_document: dict[str, Any]
    description_html: str
    description_plain_text: str
    body_schema_version: Literal[2]
    status: TicketStatus
    status_label: str
    status_code: str
    priority: Priority
    priority_label: str
    priority_code: str
    parent: TicketParentView | None
    creator: TicketUserView
    assignee: TicketUserView | None
    due_date: date | None
    actual_started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class TicketRelationTargetView(BaseModel):
    key: str
    title: str
    status: TicketStatus
    status_label: str
    status_code: str


class TicketRelationView(BaseModel):
    id: int
    relation_type: RelationType
    relation_label: str
    direction: Literal["RELATED", "OUTGOING", "INCOMING"]
    direction_label: str
    ticket: TicketRelationTargetView
    created_at: datetime


class TicketDetailView(TicketView):
    relations: list[TicketRelationView] = Field(default_factory=list)


class TicketPage(BaseModel):
    tickets: list[TicketView]
    total: int
    page: int
    page_size: int


class TicketTrashBatchView(BaseModel):
    id: int
    project_id: int
    root_ticket_key: str
    root_ticket_title: str
    root_ticket_type: TicketType
    root_ticket_type_label: str
    root_ticket_version: int
    deleted_by: TicketUserView
    deleted_at: datetime
    purge_after: datetime
    child_count: int
    is_expired: bool
    can_restore: bool


class TicketTrashPage(BaseModel):
    batches: list[TicketTrashBatchView]
    retention_days: int
    can_restore: bool


class TicketCreateOptions(BaseModel):
    assignees: list[TicketUserView]
    parents: list[TicketParentView]


class TicketEditOptions(BaseModel):
    assignees: list[TicketUserView]
    parents: list[TicketParentView]


class BoardCard(BaseModel):
    key: str
    version: int
    type: TicketType
    type_label: str
    title: str
    status: TicketStatus
    status_label: str
    status_code: str
    priority: Priority
    priority_label: str
    priority_code: str
    assignee: TicketUserView | None
    due_date: date | None
    can_transition: bool
    allowed_statuses: list[TicketStatus] = Field(default_factory=list)
    completion_blocked: bool = False


class BoardTask(BaseModel):
    card: BoardCard
    subtasks: list[BoardCard] = Field(default_factory=list)


class BoardDetachedGroup(BaseModel):
    parent_key: str
    parent_title: str
    subtasks: list[BoardCard] = Field(default_factory=list)


class BoardColumn(BaseModel):
    status: TicketStatus
    label: str
    code: str
    card_count: int
    tasks: list[BoardTask] = Field(default_factory=list)
    detached_groups: list[BoardDetachedGroup] = Field(default_factory=list)


class BoardEpicGroup(BaseModel):
    key: str | None
    title: str
    columns: list[BoardColumn]


class BoardStatusOption(BaseModel):
    status: TicketStatus
    label: str
    code: str


class BoardView(BaseModel):
    groups: list[BoardEpicGroup]
    statuses: list[BoardStatusOption]
