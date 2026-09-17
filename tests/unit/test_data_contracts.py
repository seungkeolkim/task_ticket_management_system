from copy import deepcopy
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain.serialization import canonical_json_sha256
from app.schemas.contracts import (
    ReportInput,
    ReportOutput,
    ReportPeriod,
    ReportSkillDefinition,
    TicketEvent,
    TicketFilter,
)


@pytest.fixture
def report_data() -> dict:
    before = dict(
        ticket_key="DEV-1",
        project_id=1,
        version=1,
        type="TASK",
        title="업무",
        status="TODO",
        priority="MAJOR",
        creator_id=1,
        created_at="2026-09-13T00:00:00Z",
        updated_at="2026-09-13T00:00:00Z",
    )
    after = before | {"status": "IN_PROGRESS", "version": 2}
    event = dict(
        event_key="00000000-0000-0000-0000-000000000001",
        operation_id="00000000-0000-0000-0000-000000000002",
        ticket_key="DEV-1",
        project_id=1,
        ticket_version=2,
        event_type="STATUS_CHANGED",
        actor_id=1,
        occurred_at="2026-09-14T00:00:00Z",
        before_state=before,
        after_state=after,
        changes=[{"field": "status", "before": "TODO", "after": "IN_PROGRESS"}],
    )
    return dict(
        run_key="00000000-0000-0000-0000-000000000003",
        period={"start": "2026-09-14T09:00:00+09:00", "end": "2026-09-21T09:00:00+09:00"},
        project_ids=[1],
        selection={},
        captured_at="2026-09-21T00:00:00Z",
        coverage="COMPLETE",
        tickets=[
            dict(
                source_id="ticket:DEV-1",
                ticket_key="DEV-1",
                project_id=1,
                state_at_start=before,
                state_at_end=after,
                events=[event],
            )
        ],
    )


def test_report_round_trip_and_source_validation(report_data: dict) -> None:
    report = ReportInput.model_validate(report_data)
    assert report.period.start == datetime(2026, 9, 14, tzinfo=UTC)
    assert ReportInput.model_validate_json(report.model_dump_json()) == report
    output = ReportOutput(
        title="주간보고",
        markdown="# 주간보고\n업무가 진행 중입니다.",
        cited_source_ids=["event:00000000-0000-0000-0000-000000000001"],
    )
    output.validate_sources(report)
    output.cited_source_ids = ["ticket:SECRET-1"]
    with pytest.raises(ValueError, match="not supplied"):
        output.validate_sources(report)


@pytest.mark.parametrize("time", ["2026-09-13T23:59:59Z", "2026-09-21T00:00:00Z"])
def test_report_excludes_events_outside_half_open_period(report_data: dict, time: str) -> None:
    report_data["tickets"][0]["events"][0]["occurred_at"] = time
    with pytest.raises(ValidationError, match="outside report period"):
        ReportInput.model_validate(report_data)


@pytest.mark.parametrize(
    "change",
    [
        {"project_ids": [2]},
        {"project_ids": [1, 1]},
        {"captured_at": "2026-09-20T00:00:00Z"},
        {"coverage": "PARTIAL"},
        {"schema_version": 2},
    ],
)
def test_report_rejects_inconsistent_scope_and_versions(report_data: dict, change: dict) -> None:
    with pytest.raises(ValidationError):
        ReportInput.model_validate(report_data | change)


def test_event_rejects_mismatched_before_after_and_missing_version(report_data: dict) -> None:
    event = report_data["tickets"][0]["events"][0]
    for path, value in (("project_id", 2), ("version", 99), ("ticket_key", "DEV-2")):
        modified = deepcopy(event)
        modified["after_state"][path] = value
        with pytest.raises(ValidationError):
            TicketEvent.model_validate(modified)
    with pytest.raises(ValidationError):
        TicketEvent.model_validate(event | {"before_state": None})


def test_multiple_status_changes_are_preserved(report_data: dict) -> None:
    ticket = report_data["tickets"][0]
    first = ticket["events"][0]
    second = deepcopy(first)
    second.update(
        event_key="00000000-0000-0000-0000-000000000004",
        ticket_version=3,
        occurred_at="2026-09-15T00:00:00Z",
        before_state=first["after_state"],
        after_state=first["after_state"] | {"version": 3, "status": "DONE"},
    )
    second["changes"] = [{"field": "status", "before": "IN_PROGRESS", "after": "DONE"}]
    ticket["events"].append(second)
    ticket["state_at_end"] = second["after_state"]
    report = ReportInput.model_validate(report_data)
    assert [event.after_state.status for event in report.tickets[0].events] == [
        "IN_PROGRESS",
        "DONE",
    ]


@pytest.mark.parametrize(
    "values",
    [
        {"page_size": 100},
        {"sql": "SELECT * FROM tickets"},
        {"statuses": ["UNKNOWN"]},
        {"unassigned": True, "assignee_ids": [1]},
        {"due_from": "2026-09-18", "due_through": "2026-09-17"},
        {"created_from": "2026-09-17T00:00:00"},
    ],
)
def test_saved_filter_contract_rejects_invalid_input(values: dict) -> None:
    with pytest.raises(ValidationError):
        TicketFilter.model_validate(values)


def test_report_period_and_skill_contracts() -> None:
    with pytest.raises(ValidationError):
        ReportPeriod(start="2026-09-17T00:00:00Z", end="2026-09-16T00:00:00Z")
    with pytest.raises(ValidationError):
        ReportPeriod(start="2026-09-16T00:00:00Z", end="2026-09-17T00:00:00Z", timezone="Not/AZone")
    with pytest.raises(ValidationError):
        ReportSkillDefinition(
            key="weekly-report",
            version=1,
            name="주간보고",
            description="요약",
            instructions_markdown="요약한다",
            output_contract="shell-script/v1",
        )


def test_snapshot_hash_is_order_independent_and_rejects_non_json_numbers() -> None:
    assert canonical_json_sha256({"한글": 1, "b": 2}) == canonical_json_sha256({"b": 2, "한글": 1})
    assert canonical_json_sha256({"한글": 1}) != canonical_json_sha256({"한글": 2})
    with pytest.raises(ValueError):
        canonical_json_sha256({"value": float("nan")})
