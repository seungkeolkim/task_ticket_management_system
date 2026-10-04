import unicodedata
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, model_validator

from app.schemas.contracts import TicketFilter


def normalize_saved_filter_name(value: str) -> str:
    """필터 이름을 정규화하고 빈 이름·제어 문자·과도한 길이를 거부한다."""
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or len(normalized) > 200:
        raise ValueError("필터 이름은 1~200자로 입력하세요.")
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ValueError("필터 이름에는 제어 문자를 사용할 수 없습니다.")
    return normalized


SavedFilterName = Annotated[str, AfterValidator(normalize_saved_filter_name)]


class SavedFilterCreate(BaseModel):
    """소유자·공개 범위를 서버가 지정하는 저장 필터 생성 입력이다."""

    model_config = ConfigDict(extra="forbid")
    name: SavedFilterName
    definition: TicketFilter


class SavedFilterUpdate(BaseModel):
    """이름 변경과 조건 덮어쓰기의 입력 및 동시 수정 기준이다."""

    model_config = ConfigDict(extra="forbid")
    expected_updated_at: AwareDatetime
    name: SavedFilterName | None = None
    definition: TicketFilter | None = None

    @model_validator(mode="after")
    def validate_changes(self):
        """변경 필드를 요구하고 명시적인 null 입력을 거부한다."""
        changed_fields = self.model_fields_set - {"expected_updated_at"}
        if not changed_fields or any(getattr(self, name) is None for name in changed_fields):
            raise ValueError("변경할 이름 또는 조건을 입력하세요.")
        return self


class SavedFilterDelete(BaseModel):
    """최근 조회한 필터에 대한 삭제만 허용하는 입력이다."""

    model_config = ConfigDict(extra="forbid")
    expected_updated_at: AwareDatetime
