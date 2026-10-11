"""조건 트리의 타입·규모·부정 계약과 게시된 예시를 검증한다."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.schemas.ticket_filters import TicketFilter


def condition_definition(field_name="status", operator="in", values=None):
    """테스트에서 검증할 개별 조건을 구성한다."""
    return {
        "kind": "condition",
        "field": field_name,
        "operator": operator,
        "values": values if values is not None else ["TODO"],
    }


@pytest.mark.parametrize(
    "condition",
    [
        condition_definition(values=[]),
        condition_definition(values=["UNKNOWN"]),
        condition_definition(operator="contains"),
        condition_definition("assignee", values=[True]),
        condition_definition("creator", values=["1"]),
        condition_definition("assignee", values=[-1]),
        condition_definition("status", "is_empty", []),
        condition_definition("assignee", "is_empty", [1]),
        condition_definition("search", "contains", [" "]),
        condition_definition("search", "contains", ["a" * 201]),
        condition_definition("due_date", "between", ["2026-10-02", "2026-10-01"]),
        condition_definition("created_date", "on", ["2026-10-01T00:00:00Z"]),
        condition_definition("updated_date", "on", ["0001-01-01"]),
        condition_definition("creator", values=[{"current_user": True}]),
    ],
)
def test_filter_rejects_invalid_operator_values_and_dynamic_inputs(condition):
    """허용되지 않은 조합과 아직 구현하지 않은 동적 값을 거부한다."""
    with pytest.raises(ValidationError):
        TicketFilter(expression={"children": [condition]})


def test_filter_roundtrip_and_repeated_fields():
    """반복 필드·중첩·NOT의 값과 순서가 JSON 왕복에서 보존된다."""
    definition = TicketFilter(
        expression={
            "operator": "OR",
            "children": [
                condition_definition("assignee", "in", [1, 2, 1]),
                {
                    "kind": "group",
                    "negated": True,
                    "children": [
                        condition_definition("assignee", "is_empty", []),
                        condition_definition("status", "not_in", ["DONE"]),
                    ],
                },
            ],
        }
    )
    assert definition.expression.children[0].values == [1, 2]
    assert TicketFilter.model_validate_json(definition.model_dump_json()) == definition


def test_filter_rejects_empty_nested_groups_and_resource_exhaustion():
    """빈 그룹·깊이·개수·크기 제한을 v2와 무관한 구 입력까지 함께 검사한다."""
    deep_group = {"kind": "group", "children": [condition_definition()]}
    for _ in range(5):
        deep_group = {"kind": "group", "children": [deepcopy(deep_group)]}
    invalid_definitions = [
        {"schema_version": 1},
        {"query": "v1"},
        {"expression": {"negated": True}},
        {"expression": {"children": [{"kind": "group"}]}},
        {"expression": deep_group},
        {"expression": {"children": [condition_definition()] * 60}},
        {
            "expression": {
                "children": [condition_definition("search", "contains", ["가" * 200])] * 10
            }
        },
    ]
    for definition in invalid_definitions:
        with pytest.raises(ValidationError):
            TicketFilter.model_validate(definition)
    assert TicketFilter().expression.children == []
