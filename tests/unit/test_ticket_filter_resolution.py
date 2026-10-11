"""동적 기준값의 날짜 경계·타입·현재 사용자와 원본 보존을 검증한다."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain.auth import Identity
from app.schemas.ticket_filters import TicketFilter
from app.services.ticket_filter_resolution import resolve_ticket_filter

ACTOR = Identity(42, "tester", "테스트 사용자", "조직", "USER", False, 1)


def dynamic_definition(rule, field="updated_date", operator="between", **properties):
    """중첩·부정 조합에도 사용할 수 있는 동적 조건 정의를 만든다."""
    return TicketFilter(
        expression={
            "children": [
                {
                    "kind": "condition",
                    "field": field,
                    "operator": operator,
                    "rule": rule,
                    **properties,
                }
            ]
        }
    )


@pytest.mark.parametrize(
    "reference,rule,operator,expected",
    [
        ("2026-10-11T14:59:59", {"kind": "today"}, "on", ["2026-10-11"]),
        ("2026-10-11T15:00:00", {"kind": "today"}, "after", ["2026-10-12"]),
        (
            "2026-10-11T00:00:00",
            {"kind": "relative_period", "direction": "past", "days": 7},
            "between",
            ["2026-10-05", "2026-10-11"],
        ),
        (
            "2026-10-11T00:00:00",
            {"kind": "relative_period", "direction": "future", "days": 7},
            "between",
            ["2026-10-11", "2026-10-17"],
        ),
        (
            "2026-10-11T00:00:00",
            {"kind": "relative_period", "direction": "past", "days": 1},
            "between",
            ["2026-10-11", "2026-10-11"],
        ),
        (
            "2026-10-11T00:00:00",
            {"kind": "working_week", "week": "this"},
            "between",
            ["2026-10-05", "2026-10-09"],
        ),
        (
            "2026-10-11T15:00:00",
            {"kind": "working_week", "week": "this"},
            "between",
            ["2026-10-12", "2026-10-16"],
        ),
        (
            "2026-10-09T00:00:00",
            {"kind": "working_week", "week": "last"},
            "between",
            ["2026-09-28", "2026-10-02"],
        ),
        (
            "2026-01-01T00:00:00",
            {"kind": "working_week", "week": "this"},
            "between",
            ["2025-12-29", "2026-01-02"],
        ),
        (
            "2024-03-01T00:00:00",
            {"kind": "day_offset", "direction": "past", "days": 1},
            "before",
            ["2024-02-29"],
        ),
        (
            "2026-10-11T00:00:00",
            {"kind": "day_offset", "direction": "future", "days": 7},
            "after",
            ["2026-10-18"],
        ),
    ],
)
def test_dynamic_date_resolution_preserves_rule_and_calendar_boundaries(
    reference, rule, operator, expected
):
    """한국 자정·월요일·금요일·주말·월/연도·윤일과 N일 포함 의미를 검증한다."""
    definition = dynamic_definition(rule, operator=operator, negated=True)
    original_json = definition.model_dump_json()
    resolved, metadata = resolve_ticket_filter(
        definition, ACTOR, evaluated_at=datetime.fromisoformat(reference).replace(tzinfo=UTC)
    )
    assert resolved.expression.children[0].values == expected
    assert resolved.expression.children[0].rule is None
    assert resolved.expression.children[0].negated is True
    assert metadata.conditions[0].values == expected
    assert metadata.conditions[0].path == "expression.0"
    assert definition.model_dump_json() == original_json


def test_current_user_uses_applying_identity_and_preserves_negative_operator():
    """현재 사용자는 고정 ID 후보와 무관하게 적용 actor로 해석한다."""
    definition = dynamic_definition({"kind": "current_user"}, "assignee", "not_in")
    resolved, metadata = resolve_ticket_filter(definition, ACTOR)
    assert resolved.expression.children[0].values == [42]
    assert resolved.expression.children[0].operator == "not_in"
    assert metadata.user_label == "테스트 사용자 · tester"
    assert definition.expression.children[0].values == []


@pytest.mark.parametrize(
    "rule,field,operator,values",
    [
        ({"kind": "current_user"}, "status", "in", []),
        ({"kind": "current_user"}, "creator", "is_empty", []),
        ({"kind": "today"}, "creator", "in", []),
        ({"kind": "today"}, "due_date", "between", []),
        ({"kind": "working_week", "week": "this"}, "due_date", "before", []),
        ({"kind": "relative_period", "days": 0, "direction": "past"}, "due_date", "between", []),
        ({"kind": "relative_period", "days": True, "direction": "past"}, "due_date", "between", []),
        ({"kind": "relative_period", "days": 1.5, "direction": "past"}, "due_date", "between", []),
        ({"kind": "relative_period", "days": 3651, "direction": "past"}, "due_date", "between", []),
        ({"kind": "day_offset", "days": 1, "direction": "sideways"}, "due_date", "on", []),
        ({"kind": "working_week", "week": "next"}, "due_date", "between", []),
        ({"kind": "today", "sql": "SELECT 1"}, "due_date", "on", []),
        ({"kind": "current_user"}, "creator", "in", [42]),
    ],
)
def test_dynamic_rule_rejects_invalid_fields_operators_ranges_and_mixed_values(
    rule, field, operator, values
):
    """잘못된 규칙과 고정/동적 값 동시 지정을 서버에서 거부한다."""
    with pytest.raises(ValidationError):
        dynamic_definition(rule, field, operator, values=values)


def test_resolution_rejects_naive_clock_and_old_contract():
    """호스트 시간대에 의존하는 시각과 구형 입력을 허용하지 않는다."""
    with pytest.raises(ValueError):
        resolve_ticket_filter(TicketFilter(), ACTOR, evaluated_at=datetime(2026, 10, 12))
    with pytest.raises(ValidationError):
        TicketFilter(schema_version=2)
