"""Validate ticket-local property input without sharing project field definitions."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.ticket_properties import TicketCustomField
from app.schemas.tickets import TicketCreate, TicketUpdate


def test_labels_are_free_normalized_and_deduplicated() -> None:
    """사전 목록 없이 Unicode·공백·대소문자 중복을 정리한다."""
    payload = TicketCreate(title="업무", labels=[" 보안 ", "Security", "security", "보안"])
    assert payload.labels == ["보안", "Security"]


def test_text_fields_have_stable_identity_and_preserve_multiline_text() -> None:
    """Text 필드가 고유 ID·타입과 공백을 포함한 값을 보존한다."""
    custom_field = TicketCustomField(name=" 방문 장소 ", value="  첫째 줄\n둘째 줄  ")
    assert isinstance(custom_field.field_id, UUID)
    assert custom_field.name == "방문 장소"
    assert custom_field.field_type == "TEXT"
    assert custom_field.value == "  첫째 줄\n둘째 줄  "
    assert TicketCustomField.model_validate(custom_field.model_dump()) == custom_field


@pytest.mark.parametrize(
    "properties",
    [
        {"labels": [" "]},
        {"labels": ["a\nb"]},
        {"labels": ["x" * 65]},
        {"labels": ["\u0344" * 64]},
        {"labels": [str(number) for number in range(31)]},
        {"labels": None},
        {"custom_fields": None},
        {"custom_fields": [{"name": "  "}]},
        {"custom_fields": [{"name": "\u0344" * 100}]},
        {"custom_fields": [{"name": "날짜", "field_type": "DATE", "value": "2026-10-03"}]},
        {"custom_fields": [{"name": "숫자", "value": 42}]},
        {"custom_fields": [{"name": "이름", "value": "x" * 10001}]},
        {"custom_fields": [{"name": "Name"}, {"name": " name "}]},
        {"custom_fields": [{"name": str(number)} for number in range(31)]},
    ],
)
def test_invalid_properties_are_rejected(properties: dict) -> None:
    """미지원 타입·중복·크기 제한 위반을 API 계약에서 차단한다."""
    with pytest.raises(ValidationError):
        TicketCreate(title="업무", **properties)


def test_duplicate_field_identifiers_are_rejected() -> None:
    """서로 다른 이름이라도 같은 ID를 가진 필드는 거부한다."""
    custom_field = TicketCustomField(name="첫 필드").model_dump(mode="json")
    with pytest.raises(ValidationError):
        TicketCreate(
            title="업무", custom_fields=[custom_field, custom_field | {"name": "다른 이름"}]
        )


def test_update_distinguishes_omission_from_explicit_removal() -> None:
    """이전 API 호출의 생략과 명시적 빈 목록 삭제를 구분한다."""
    payload = TicketUpdate(title="업무", priority="MAJOR", expected_version=1)
    assert "labels" not in payload.model_fields_set
    assert "custom_fields" not in payload.model_fields_set
    cleared = TicketUpdate(
        title="업무", priority="MAJOR", expected_version=1, labels=[], custom_fields=[]
    )
    assert {"labels", "custom_fields"} <= cleared.model_fields_set
