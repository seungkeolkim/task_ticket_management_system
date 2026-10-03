"""Ticket-local labels and typed ad-hoc property contracts."""

import unicodedata
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator


def normalize_property_name(value: str) -> str:
    """표시 이름의 Unicode·주변 공백을 정리하고 제어 문자를 거부한다."""
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or any(
        unicodedata.category(character).startswith("C") for character in normalized
    ):
        raise ValueError("이름은 비어 있거나 제어 문자를 포함할 수 없습니다.")
    return normalized


class TicketCustomField(BaseModel):
    """재사용 정의 없이 하나의 ticket에 속하는 타입 구분 가능한 값이다."""

    model_config = ConfigDict(extra="forbid")

    field_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=100)
    field_type: Literal["TEXT"] = "TEXT"
    value: str = Field(default="", max_length=10000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """이름을 공통 표시 이름 규칙으로 정규화한다."""
        normalized = normalize_property_name(value)
        if len(normalized) > 100:
            raise ValueError("정규화한 필드 이름은 100자 이하여야 합니다.")
        return normalized


def normalize_labels(values: list[str]) -> list[str]:
    """순서를 보존하며 동일 이름의 Label을 한 번만 저장한다."""
    labels = []
    seen_names = set()
    for value in values:
        normalized = normalize_property_name(value)
        if len(normalized) > 64:
            raise ValueError("정규화한 Label은 64자 이하여야 합니다.")
        identity = normalized.casefold()
        if identity not in seen_names:
            labels.append(normalized)
            seen_names.add(identity)
    return labels


def validate_custom_fields(values: list[TicketCustomField]) -> list[TicketCustomField]:
    """하나의 ticket 안에서 필드 ID와 정규화된 이름 중복을 거부한다."""
    seen_identifiers = set()
    seen_names = set()
    for custom_field in values:
        identity = custom_field.name.casefold()
        if custom_field.field_id in seen_identifiers or identity in seen_names:
            raise ValueError("추가 필드의 이름과 ID는 ticket 안에서 중복될 수 없습니다.")
        seen_identifiers.add(custom_field.field_id)
        seen_names.add(identity)
    return values


TicketLabels = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=64)]],
    Field(max_length=30),
    AfterValidator(normalize_labels),
]
TicketCustomFields = Annotated[
    list[TicketCustomField], Field(max_length=30), AfterValidator(validate_custom_fields)
]
