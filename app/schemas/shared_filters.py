from typing import Literal

from pydantic import AwareDatetime, BaseModel

from app.schemas.contracts import TicketFilter
from app.schemas.saved_filter_inputs import SavedFilterCreate, SavedFilterDelete, SavedFilterUpdate


class SharedFilterCreate(SavedFilterCreate):
    """공유 필터의 Create 입력 계약이다."""


class SharedFilterUpdate(SavedFilterUpdate):
    """공유 필터의 Update 입력 계약이다."""


class SharedFilterDelete(SavedFilterDelete):
    """공유 필터의 Delete 입력 계약이다."""


class SharedFilterSummary(BaseModel):
    """조건이 손상되었더라도 관리 가능한 공유 필터 요약이다."""

    id: int
    name: str
    visibility: Literal["PROJECT"] = "PROJECT"
    updated_at: AwareDatetime


class SharedFilterView(SharedFilterSummary):
    """현재 프로젝트 범위와 schema를 재검증한 저장 조건이다."""

    definition: TicketFilter
