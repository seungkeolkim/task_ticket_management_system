"""고정값과 동적 기준값을 검증된 조건 트리로 표현하는 티켓 필터 v3 계약이다."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    model_serializer,
    model_validator,
)

from app.domain.codes import Priority, TicketStatus, TicketType

MAX_FILTER_BYTES = 4096
MAX_FILTER_NODES = 60
MAX_FILTER_DEPTH = 5
MAX_CONDITION_VALUES = 30


class CurrentUserRule(BaseModel):
    """필터를 적용하는 인증된 사용자를 참조한다."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["current_user"] = "current_user"


class TodayRule(BaseModel):
    """요청 기준의 한국 날짜를 참조한다."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["today"] = "today"


class DayOffsetRule(BaseModel):
    """오늘에서 지정한 달력 일수 전후의 날짜를 참조한다."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["day_offset"] = "day_offset"
    days: StrictInt = Field(ge=1, le=3650)
    direction: Literal["past", "future"]


class RelativePeriodRule(BaseModel):
    """오늘을 포함하는 총 N개 달력 날짜의 기간을 참조한다."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["relative_period"] = "relative_period"
    days: StrictInt = Field(ge=1, le=3650)
    direction: Literal["past", "future"]


class WorkingWeekRule(BaseModel):
    """이번 또는 지난 달력 주의 월요일부터 금요일까지를 참조한다."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["working_week"] = "working_week"
    week: Literal["this", "last"]


DynamicFilterRule = Annotated[
    CurrentUserRule | TodayRule | DayOffsetRule | RelativePeriodRule | WorkingWeekRule,
    Field(discriminator="kind"),
]


class ResolvedFilterCondition(BaseModel):
    """조건 트리 위치와 이번 요청에서 계산한 동적 값을 공개한다."""

    path: str
    field: str
    values: list[str | int]


class FilterResolution(BaseModel):
    """조회·count·화면 설명이 공유하는 요청별 기준과 해석 결과다."""

    evaluated_at: datetime
    reference_date: date
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"
    user_id: int
    user_label: str
    conditions: list[ResolvedFilterCondition] = Field(default_factory=list)


class FilterCondition(BaseModel):
    """필드별 허용 연산자와 고정값을 검증하는 개별 조건이다."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["condition"] = "condition"
    field: Literal[
        "search",
        "type",
        "status",
        "priority",
        "epic",
        "parent",
        "creator",
        "assignee",
        "created_date",
        "updated_date",
        "due_date",
    ]
    operator: Literal[
        "in",
        "not_in",
        "contains",
        "not_contains",
        "is_empty",
        "is_not_empty",
        "on",
        "before",
        "after",
        "between",
    ]
    values: list[StrictStr | StrictInt] = Field(default_factory=list, max_length=30)
    rule: DynamicFilterRule | None = None
    negated: bool = False

    @model_serializer(mode="wrap")
    def serialize_condition(self, serializer):
        """고정 조건에는 불필요한 null 규칙을 추가하지 않아 기존 크기를 보존한다."""
        serialized_condition = serializer(self)
        if self.rule is None:
            serialized_condition.pop("rule", None)
        return serialized_condition

    @model_validator(mode="after")
    def validate_condition(self) -> Self:
        """필드·연산자·값의 조합을 검증하고 날짜 및 선택값을 정규화한다."""
        if self.rule is not None:
            if self.values:
                raise ValueError("고정값과 동적 규칙을 함께 지정할 수 없습니다.")
            if isinstance(self.rule, CurrentUserRule):
                if self.field not in {"creator", "assignee"} or self.operator not in {
                    "in",
                    "not_in",
                }:
                    raise ValueError("현재 사용자 조건의 필드·연산자를 확인하세요.")
            else:
                if self.field not in {"created_date", "updated_date", "due_date"}:
                    raise ValueError("날짜 규칙은 날짜 필드에만 사용할 수 있습니다.")
                allowed_operators = (
                    {"between"}
                    if isinstance(self.rule, (RelativePeriodRule, WorkingWeekRule))
                    else {"on", "before", "after"}
                )
                if self.operator not in allowed_operators:
                    raise ValueError("날짜 규칙의 연산자를 확인하세요.")
            return self
        empty_operators = {"is_empty", "is_not_empty"}
        if self.operator in empty_operators:
            if self.field not in {"assignee", "parent", "due_date"} or self.values:
                raise ValueError("이 필드의 빈 값 조건을 확인하세요.")
            return self
        if not self.values:
            raise ValueError("조건 값을 선택하세요.")
        if self.field == "search":
            if self.operator not in {"contains", "not_contains"} or len(self.values) != 1:
                raise ValueError("검색 연산자를 확인하세요.")
            search_value = self.values[0]
            if not isinstance(search_value, str) or not search_value.strip():
                raise ValueError("검색어를 입력하세요.")
            if len(search_value.strip()) > 200:
                raise ValueError("검색어는 200자 이하여야 합니다.")
            self.values = [search_value.strip()]
        elif self.field in {"created_date", "updated_date", "due_date"}:
            expected_count = 2 if self.operator == "between" else 1
            if self.operator not in {"on", "before", "after", "between"}:
                raise ValueError("날짜 연산자를 확인하세요.")
            if len(self.values) != expected_count:
                raise ValueError("날짜 경계를 확인하세요.")
            for date_value in self.values:
                if not isinstance(date_value, str) or len(date_value) != 10:
                    raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다.")
                parsed_date = date.fromisoformat(date_value)
                if not date(2, 1, 1) <= parsed_date <= date(9998, 12, 31):
                    raise ValueError("날짜 범위를 확인하세요.")
            if expected_count == 2 and self.values[0] > self.values[1]:
                raise ValueError("날짜 범위가 역순입니다.")
        else:
            if self.operator not in {"in", "not_in"}:
                raise ValueError("선택 연산자를 확인하세요.")
            enum_values = {
                "type": {item.value for item in TicketType},
                "status": {item.value for item in TicketStatus},
                "priority": {item.value for item in Priority},
            }
            if self.field in enum_values:
                if any(value not in enum_values[self.field] for value in self.values):
                    raise ValueError("선택할 수 없는 값입니다.")
            elif any(type(value) is not int or value <= 0 for value in self.values):
                raise ValueError("참조 ID는 양의 정수여야 합니다.")
            self.values = list(dict.fromkeys(self.values))
        return self


class FilterGroup(BaseModel):
    """조건 또는 그룹의 결과를 AND/OR로 묶고 선택적으로 반전한다."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["group"] = "group"
    operator: Literal["AND", "OR"] = "AND"
    children: list[Annotated[FilterCondition | FilterGroup, Field(discriminator="kind")]] = Field(
        default_factory=list, max_length=MAX_FILTER_NODES
    )
    negated: bool = False


FilterGroup.model_rebuild()


class TicketFilter(BaseModel):
    """목록·칸반·저장·URL에서 동일하게 사용하는 v3 조건 및 조회 설정이다."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[3] = 3
    expression: FilterGroup = Field(default_factory=FilterGroup)
    sort_by: Literal["created_at", "updated_at", "due_date", "priority", "number"] = "updated_at"
    sort_direction: Literal["asc", "desc"] = "desc"
    page_size: Literal[10, 20, 50] = 20

    @model_validator(mode="after")
    def validate_expression_limits(self) -> Self:
        """조건 규모를 제한하고 빈 하위 그룹 및 반전된 빈 최상위를 거부한다."""
        pending_groups = [(self.expression, 1)]
        total_nodes = 0
        while pending_groups:
            current_node, current_depth = pending_groups.pop()
            total_nodes += 1
            if total_nodes > MAX_FILTER_NODES or current_depth > MAX_FILTER_DEPTH:
                raise ValueError("조건 개수 또는 중첩 깊이가 허용 범위를 초과했습니다.")
            if isinstance(current_node, FilterGroup):
                if not current_node.children and (current_depth > 1 or current_node.negated):
                    raise ValueError("빈 그룹을 제거하거나 조건을 추가하세요.")
                for child_node in current_node.children:
                    pending_groups.append((child_node, current_depth + 1))
        if len(self.model_dump_json().encode("utf-8")) > MAX_FILTER_BYTES:
            raise ValueError("필터 크기는 4 KiB 이하여야 합니다.")
        return self


def iter_filter_conditions(expression: FilterGroup) -> Iterator[FilterCondition]:
    """모든 하위 그룹의 조건을 순서대로 순회한다."""
    for child_node in expression.children:
        if isinstance(child_node, FilterCondition):
            yield child_node
        else:
            yield from iter_filter_conditions(child_node)


def serialize_ticket_filter(ticket_filter: TicketFilter) -> str:
    """동일한 URL과 비교에 사용할 공백 없는 JSON을 반환한다."""
    return json.dumps(
        ticket_filter.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
    )
