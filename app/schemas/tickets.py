from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.codes import Priority, TicketStatus, TicketType


class TicketCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: TicketType = TicketType.TASK
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=100_000)
    priority: Priority = Priority.MAJOR
    parent_key: str | None = Field(default=None, max_length=64)
    assignee_id: int | None = Field(default=None, gt=0)
    due_date: date | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("제목을 입력하세요.")
        return normalized

    @field_validator("parent_key", mode="before")
    @classmethod
    def normalize_parent_key(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip().upper()
        return normalized or None

    @model_validator(mode="after")
    def validate_parent_shape(self):
        if self.type == TicketType.EPIC and self.parent_key is not None:
            raise ValueError("Epic은 상위 티켓을 가질 수 없습니다.")
        if self.type == TicketType.SUBTASK and self.parent_key is None:
            raise ValueError("Subtask는 상위 Task가 필요합니다.")
        return self


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
    number: int
    key: str
    type: TicketType
    type_label: str
    title: str
    description: str
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
    version: int
    created_at: datetime
    updated_at: datetime


class TicketPage(BaseModel):
    tickets: list[TicketView]
    total: int
    page: int
    page_size: int


class TicketCreateOptions(BaseModel):
    assignees: list[TicketUserView]
    parents: list[TicketParentView]
