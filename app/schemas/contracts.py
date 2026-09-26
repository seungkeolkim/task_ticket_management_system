"""Version 1 storage/exchange contracts, independent of a web editor or LLM vendor."""

from datetime import UTC, date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from app.domain.codes import HistoryEventType, Priority, RelationType, TicketStatus, TicketType
from app.domain.rich_text import empty_body_document, validate_body_document

PositiveId = Annotated[int, Field(gt=0)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TicketFilter(Contract):
    schema_version: Literal[1] = 1
    query: str = Field(default="", max_length=200)
    types: list[TicketType] = Field(default_factory=list)
    statuses: list[TicketStatus] = Field(default_factory=list)
    priorities: list[Priority] = Field(default_factory=list)
    epic_id: PositiveId | None = None
    parent_id: PositiveId | None = None
    creator_ids: list[PositiveId] = Field(default_factory=list)
    assignee_ids: list[PositiveId] = Field(default_factory=list)
    unassigned: bool = False
    created_from: AwareDatetime | None = None
    created_before: AwareDatetime | None = None
    updated_from: AwareDatetime | None = None
    updated_before: AwareDatetime | None = None
    due_from: date | None = None
    due_through: date | None = None
    sort_by: Literal["created_at", "updated_at", "due_date", "priority", "number"] = "updated_at"
    sort_direction: Literal["asc", "desc"] = "desc"
    page_size: Literal[10, 20, 50] = 20

    @model_validator(mode="after")
    def valid_filters(self) -> Self:
        """저장 필터의 필드와 연산자 조합을 검증한다."""
        if self.unassigned and self.assignee_ids:
            raise ValueError("unassigned and assignee_ids are mutually exclusive")
        for start, end in (
            (self.created_from, self.created_before),
            (self.updated_from, self.updated_before),
        ):
            if start is not None and end is not None and start >= end:
                raise ValueError("timestamp filters use a nonempty half-open interval")
        if self.due_from and self.due_through and self.due_from > self.due_through:
            raise ValueError("due date range is reversed")
        return self


class RelationSnapshot(Contract):
    source_ticket_key: str
    target_ticket_key: str
    relation_type: RelationType
    dependency_kind: Literal["FS", "SS", "FF", "SF"] | None = None
    lag_days: int = 0

    @model_validator(mode="after")
    def valid_relation(self) -> Self:
        """티켓 관계 snapshot의 필수 필드를 검증한다."""
        if self.source_ticket_key == self.target_ticket_key:
            raise ValueError("a ticket cannot relate to itself")
        if self.relation_type == RelationType.DEPENDS_ON and self.dependency_kind is None:
            raise ValueError("dependencies require a scheduling kind")
        if self.relation_type == RelationType.RELATED and (
            self.dependency_kind is not None or self.lag_days != 0
        ):
            raise ValueError("related tickets have no scheduling constraint")
        return self


class TicketState(Contract):
    schema_version: Literal[2] = 2
    ticket_key: str
    project_id: PositiveId
    version: PositiveId
    type: TicketType
    title: str = Field(min_length=1, max_length=200)
    description_document: dict[str, JsonValue] = Field(default_factory=empty_body_document)
    body_schema_version: Literal[2] = 2
    status: TicketStatus
    priority: Priority
    parent_key: str | None = None
    creator_id: PositiveId
    created_at: AwareDatetime
    updated_at: AwareDatetime
    assignee_id: PositiveId | None = None
    due_date: date | None = None
    planned_start_date: date | None = None
    planned_end_date: date | None = None
    actual_started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    cancelled_at: AwareDatetime | None = None
    progress_percent: int = Field(default=0, ge=0, le=100)
    is_milestone: bool = False
    sort_order: str = "0"
    deleted_at: AwareDatetime | None = None
    relations: list[RelationSnapshot] = Field(default_factory=list)

    @field_validator("description_document")
    @classmethod
    def valid_description_document(
        cls, value: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        """이력 snapshot의 설명 문서를 공통 본문 계약으로 검증한다."""
        return validate_body_document(value)

    @model_validator(mode="after")
    def valid_state(self) -> Self:
        """티켓 상태 snapshot의 필드 일관성을 검증한다."""
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.planned_start_date and self.planned_end_date:
            if self.planned_start_date > self.planned_end_date:
                raise ValueError("planned dates are reversed")
        if self.type == TicketType.EPIC and self.parent_key is not None:
            raise ValueError("epics cannot have parents")
        if self.type == TicketType.SUBTASK and self.parent_key is None:
            raise ValueError("subtasks require a parent")
        if self.parent_key == self.ticket_key:
            raise ValueError("ticket cannot be its own parent")
        return self


class FieldChange(Contract):
    field: str = Field(min_length=1, max_length=100)
    before: JsonValue
    after: JsonValue


class TicketEvent(Contract):
    schema_version: Literal[2] = 2
    event_key: UUID
    operation_id: UUID
    ticket_key: str
    project_id: PositiveId
    ticket_version: PositiveId
    event_type: HistoryEventType
    actor_id: PositiveId
    occurred_at: AwareDatetime
    before_state: TicketState | None
    after_state: TicketState
    changes: list[FieldChange]

    @model_validator(mode="after")
    def matching_states(self) -> Self:
        """states 일치 여부를 검증한다."""
        for state in (self.before_state, self.after_state):
            if state and (
                state.project_id != self.project_id or state.ticket_key != self.ticket_key
            ):
                raise ValueError("event and state identity differ")
        if self.after_state.version != self.ticket_version:
            raise ValueError("event and resulting ticket versions differ")
        if self.event_type == HistoryEventType.CREATED:
            if self.before_state is not None or self.ticket_version != 1:
                raise ValueError("creation requires version 1 and no previous state")
        elif self.before_state is None or self.before_state.version + 1 != self.ticket_version:
            raise ValueError("changes require the immediately preceding state")
        return self


class ReportPeriod(Contract):
    start: AwareDatetime
    end: AwareDatetime
    timezone: str = Field(default="Asia/Seoul", min_length=1, max_length=100)

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        """timezone 지원 여부를 검증한다."""
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("report timezone must be a valid IANA zone") from exc
        return value

    @field_validator("start", "end")
    @classmethod
    def normalize_utc(cls, value: datetime) -> datetime:
        """utc 값을 정규화한다."""
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid_period(self) -> Self:
        """보고서 기간의 시작·종료 순서를 검증한다."""
        if self.start >= self.end:
            raise ValueError("report period must be a nonempty [start, end) interval")
        return self


class ReportTicketEvidence(Contract):
    source_id: str = Field(pattern=r"^ticket:[A-Za-z0-9_-]+$")
    ticket_key: str
    project_id: PositiveId
    state_at_start: TicketState | None
    state_at_end: TicketState | None
    events: list[TicketEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def matching_sources(self) -> Self:
        """sources 일치 여부를 검증한다."""
        if self.source_id != f"ticket:{self.ticket_key}":
            raise ValueError("source ID must identify the ticket")
        for state in (self.state_at_start, self.state_at_end):
            if state and (
                state.project_id != self.project_id or state.ticket_key != self.ticket_key
            ):
                raise ValueError("evidence and state identity differ")
        for event in self.events:
            if event.project_id != self.project_id or event.ticket_key != self.ticket_key:
                raise ValueError("evidence and event identity differ")
        return self


class ReportInput(Contract):
    schema_version: Literal[1] = 1
    run_key: UUID
    period: ReportPeriod
    project_ids: list[PositiveId] = Field(min_length=1)
    selection: TicketFilter
    captured_at: AwareDatetime
    coverage: Literal["COMPLETE", "PARTIAL"]
    coverage_notes: list[str] = Field(default_factory=list)
    tickets: list[ReportTicketEvidence]

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        """scope 값을 검증한다."""
        if len(self.project_ids) != len(set(self.project_ids)):
            raise ValueError("project IDs must be unique")
        if self.captured_at < self.period.end:
            raise ValueError("report period must end before data capture")
        if self.coverage == "PARTIAL" and not self.coverage_notes:
            raise ValueError("partial coverage requires an explanation")
        seen: set[str] = set()
        events: set[UUID] = set()
        for ticket in self.tickets:
            if ticket.project_id not in self.project_ids or ticket.source_id in seen:
                raise ValueError("duplicate or out-of-scope ticket evidence")
            seen.add(ticket.source_id)
            for event in ticket.events:
                if not self.period.start <= event.occurred_at < self.period.end:
                    raise ValueError("event is outside report period")
                if event.event_key in events:
                    raise ValueError("duplicate event evidence")
                events.add(event.event_key)
        return self

    def evidence_ids(self) -> set[str]:
        """보고서 근거 ID 목록을 반환한다."""
        return {ticket.source_id for ticket in self.tickets} | {
            f"event:{event.event_key}" for ticket in self.tickets for event in ticket.events
        }


class ReportOutput(Contract):
    schema_version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=200)
    markdown: str = Field(min_length=1)
    cited_source_ids: list[str]
    warnings: list[str] = Field(default_factory=list)

    def validate_sources(self, report_input: ReportInput) -> None:
        """sources 값을 검증한다."""
        if not set(self.cited_source_ids) <= report_input.evidence_ids():
            raise ValueError("report cites evidence that was not supplied")


class ReportSkillDefinition(Contract):
    schema_version: Literal[1] = 1
    key: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=100)
    version: PositiveId
    name: str = Field(min_length=1, max_length=200)
    description: str
    instructions_markdown: str = Field(min_length=1)
    input_contract: Literal["report-input/v1"] = "report-input/v1"
    output_contract: Literal["report-output/v1"] = "report-output/v1"
    generation_defaults: dict[str, JsonValue] = Field(default_factory=dict)
