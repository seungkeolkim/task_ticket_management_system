"""주 요일과 독립 날짜 경계의 해석·검증·원본 보존을 확인한다."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from test_ticket_filter_resolution import ACTOR, dynamic_definition

from app.domain.auth import AuthError
from app.services.ticket_filter_resolution import resolve_ticket_filter


@pytest.mark.parametrize(
    "reference,rule,operator,expected",
    [
        ("2026-10-12", {"kind": "week_day", "week": "this", "weekday": 4}, "on", ["2026-10-16"]),
        (
            "2026-10-12",
            {"kind": "week_day", "week": "last", "weekday": 4},
            "before",
            ["2026-10-09"],
        ),
        ("2026-10-11", {"kind": "week_day", "week": "this", "weekday": 0}, "after", ["2026-10-05"]),
        (
            "2026-10-12",
            {
                "kind": "date_range",
                "start": {"kind": "week_day", "week": "last", "weekday": 0},
                "end": {"kind": "week_day", "week": "last", "weekday": 4},
            },
            "between",
            ["2026-10-05", "2026-10-09"],
        ),
        (
            "2026-01-01",
            {
                "kind": "date_range",
                "start": {"kind": "week_day", "week": "this", "weekday": 0},
                "end": {"kind": "week_day", "week": "this", "weekday": 4},
            },
            "between",
            ["2025-12-29", "2026-01-02"],
        ),
        (
            "2026-10-12",
            {
                "kind": "date_range",
                "start": {"kind": "fixed_date", "value": "2026-10-02"},
                "end": {"kind": "week_day", "week": "last", "weekday": 4},
            },
            "between",
            ["2026-10-02", "2026-10-09"],
        ),
        (
            "2026-10-12",
            {
                "kind": "date_range",
                "start": {"kind": "day_offset", "days": 7, "direction": "past"},
                "end": {"kind": "today"},
            },
            "between",
            ["2026-10-05", "2026-10-12"],
        ),
        (
            "2026-10-12",
            {
                "kind": "date_range",
                "start": {"kind": "today"},
                "end": {"kind": "week_day", "week": "this", "weekday": 4},
            },
            "between",
            ["2026-10-12", "2026-10-16"],
        ),
        (
            "2026-10-12",
            {"kind": "date_range", "start": {"kind": "today"}, "end": {"kind": "today"}},
            "between",
            ["2026-10-12", "2026-10-12"],
        ),
    ],
)
def test_weekday_and_independent_date_boundaries(reference, rule, operator, expected):
    """단일 요일과 고정·동적 경계의 혼합을 동일한 요청 날짜로 해석한다."""
    definition = dynamic_definition(rule, operator=operator)
    original = definition.model_dump_json()
    resolved, metadata = resolve_ticket_filter(
        definition, ACTOR, evaluated_at=datetime.fromisoformat(reference).replace(tzinfo=UTC)
    )
    assert resolved.expression.children[0].values == expected
    assert metadata.conditions[0].values == expected
    assert definition.model_dump_json() == original


@pytest.mark.parametrize(
    "rule",
    [
        {"kind": "week_day", "week": "this", "weekday": True},
        {"kind": "week_day", "week": "this", "weekday": "4"},
        {"kind": "week_day", "week": "this", "weekday": -1},
        {"kind": "week_day", "week": "this", "weekday": 7},
        {"kind": "week_day", "week": "next", "weekday": 4},
        {"kind": "date_range", "start": {"kind": "today"}},
        {"kind": "date_range", "start": {"kind": "current_user"}, "end": {"kind": "today"}},
        {
            "kind": "date_range",
            "start": {"kind": "fixed_date", "value": "2026-02-30"},
            "end": {"kind": "today"},
        },
        {
            "kind": "date_range",
            "start": {"kind": "fixed_date", "value": "2026-10-12"},
            "end": {"kind": "fixed_date", "value": "2026-10-09"},
        },
    ],
)
def test_invalid_weekday_and_date_anchor_shapes(rule):
    """경계 누락·잘못된 타입·날짜·고정 역순을 저장 전에 거부한다."""
    operator = "between" if rule["kind"] == "date_range" else "on"
    with pytest.raises(ValidationError):
        dynamic_definition(rule, operator=operator)


def test_dynamic_range_rejects_reverse_order_after_resolution():
    """지난주 금요일부터 월요일의 역순은 자동 교환하지 않고 안내한다."""
    definition = dynamic_definition(
        {
            "kind": "date_range",
            "start": {"kind": "week_day", "week": "last", "weekday": 4},
            "end": {"kind": "week_day", "week": "last", "weekday": 0},
        }
    )
    with pytest.raises(AuthError, match="기간 시작은 종료보다 늦을 수 없습니다"):
        resolve_ticket_filter(definition, ACTOR, evaluated_at=datetime(2026, 10, 12, tzinfo=UTC))
