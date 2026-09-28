import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    administrator_id: int = Field(gt=0)

    @field_validator("key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        """key 값을 정규화한다."""
        value = value.upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9]{1,31}", value):
            raise ValueError("프로젝트 키는 영문자로 시작하는 영문·숫자 2~32자입니다.")
        return value


class ProjectUpdate(BaseModel):
    """프로젝트 기본 정보와 활성 상태 변경 입력을 검증한다."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_changed_fields(self):
        """최소 한 필드와 명시적인 non-null 값을 요구한다."""
        if not self.model_fields_set:
            raise ValueError("변경할 프로젝트 정보를 입력하세요.")
        if any(getattr(self, field_name) is None for field_name in self.model_fields_set):
            raise ValueError("프로젝트 정보에는 null을 사용할 수 없습니다.")
        return self


class MemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field(gt=0)
    role: Literal["PROJECT_ADMIN", "PROJECT_USER", "PROJECT_GUEST"] = "PROJECT_USER"


class MemberRoleUpdate(BaseModel):
    """프로젝트 참여자 역할 변경 입력을 검증한다."""

    model_config = ConfigDict(extra="forbid")
    role: Literal["PROJECT_ADMIN", "PROJECT_USER", "PROJECT_GUEST"]


class ProjectView(BaseModel):
    id: int
    key: str
    name: str
    description: str
    is_active: bool
    role: str | None
    can_manage: bool


class MemberView(BaseModel):
    id: int
    user_id: int
    login_id: str
    display_name: str
    role: str
    is_active: bool


class CandidateView(BaseModel):
    id: int
    login_id: str
    display_name: str


class ProjectPage(BaseModel):
    projects: list[ProjectView]
    total: int
    page: int
    page_size: int


class ProjectDetail(BaseModel):
    project: ProjectView
    members: list[MemberView]
