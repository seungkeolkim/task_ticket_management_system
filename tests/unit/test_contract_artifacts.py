import json
import os

from app.domain.rich_text import extract_body_document_text, validate_body_document
from app.schemas.contracts import (
    ReportInput,
    ReportOutput,
    ReportSkillDefinition,
    TicketEvent,
    TicketFilter,
)


def read_artifact(name: str) -> dict:
    """계약 artifact JSON을 읽는다."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    with open(os.path.join(root, "docs", "contracts", name), encoding="utf-8") as handle:
        return json.load(handle)


def test_published_json_schemas_match_python_contracts() -> None:
    """schema·계약 관련 동작을 검증한다."""
    for artifact_name, model in (
        ("ticket-filter.v1.schema.json", TicketFilter),
        ("ticket-event.v2.schema.json", TicketEvent),
        ("report-input.v1.schema.json", ReportInput),
        ("report-output.v1.schema.json", ReportOutput),
        ("report-skill.v1.schema.json", ReportSkillDefinition),
    ):
        assert read_artifact(artifact_name) == model.model_json_schema()


def test_weekly_report_examples_are_valid_and_cite_supplied_evidence() -> None:
    """보고서 관련 동작을 검증한다."""
    data = ReportInput.model_validate(read_artifact("weekly-report-input.v1.json"))
    output = ReportOutput.model_validate(read_artifact("weekly-report-output.v1.json"))
    skill = ReportSkillDefinition.model_validate(read_artifact("weekly-report-skill.v1.json"))
    output.validate_sources(data)
    assert skill.input_contract == "report-input/v1"
    assert data.tickets[0].events[0].after_state.status == "IN_PROGRESS"
    assert "주간보고" in output.markdown


def test_korean_tiptap_body_example_matches_server_contract() -> None:
    """게시된 한국어 Tiptap 예시가 서버 body schema v2 검증을 통과하는지 확인한다."""
    document = validate_body_document(read_artifact("tiptap-body.v2.example.ko.json"))
    assert "배포 준비" in extract_body_document_text(document)
