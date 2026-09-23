import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    administrator_id: int = Field(gt=0)

    @field_validator("key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        value = value.upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9]{1,31}", value):
            raise ValueError("프로젝트 키는 영문자로 시작하는 영문·숫자 2~32자입니다.")
        return value


class MemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field(gt=0)
    role: Literal["PROJECT_ADMIN", "PROJECT_USER", "PROJECT_GUEST"] = "PROJECT_USER"


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
