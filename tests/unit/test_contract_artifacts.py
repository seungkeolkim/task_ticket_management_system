import json
import os

from app.schemas.contracts import (
    ReportInput,
    ReportOutput,
    ReportSkillDefinition,
    TicketEvent,
    TicketFilter,
)


def read_artifact(name: str) -> dict:
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    with open(os.path.join(root, "docs", "contracts", name), encoding="utf-8") as handle:
        return json.load(handle)


def test_published_json_schemas_match_python_contracts() -> None:
    for name, model in (
        ("ticket-filter", TicketFilter),
        ("ticket-event", TicketEvent),
        ("report-input", ReportInput),
        ("report-output", ReportOutput),
        ("report-skill", ReportSkillDefinition),
    ):
        assert read_artifact(f"{name}.v1.schema.json") == model.model_json_schema()


def test_weekly_report_examples_are_valid_and_cite_supplied_evidence() -> None:
    data = ReportInput.model_validate(read_artifact("weekly-report-input.v1.json"))
    output = ReportOutput.model_validate(read_artifact("weekly-report-output.v1.json"))
    skill = ReportSkillDefinition.model_validate(read_artifact("weekly-report-skill.v1.json"))
    output.validate_sources(data)
    assert skill.input_contract == "report-input/v1"
    assert data.tickets[0].events[0].after_state.status == "IN_PROGRESS"
    assert "주간보고" in output.markdown
