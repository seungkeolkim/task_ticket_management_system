"""Shared creation inputs and explicit public DTOs for administrator screens."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


def normalize_optional_email(value: str | None) -> str | None:
    """선택 이메일을 정규화하고 기본 형식을 검증한다."""
    if not value:
        return None
    normalized_email = value.lower()
    if (
        normalized_email.count("@") != 1
        or any(char.isspace() or ord(char) < 32 for char in normalized_email)
        or not all(normalized_email.split("@"))
    ):
        raise ValueError("이메일 형식을 확인하세요.")
    return normalized_email


class OrganizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    parent_id: int | None = Field(default=None, gt=0)
    description: str = Field(default="", max_length=4000)


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    login_id: str = Field(min_length=3, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    organization_id: int = Field(gt=0)
    system_role: Literal["USER", "SYSTEM_ADMIN"] = "USER"
    password: SecretStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        """이메일 값을 정규화한다."""
        return normalize_optional_email(value)


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    display_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    organization_id: int = Field(gt=0)
    system_role: Literal["USER", "SYSTEM_ADMIN"]
    is_active: bool

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        """이메일 값을 정규화한다."""
        return normalize_optional_email(value)


class UserPasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    temporary_password: SecretStr
    confirmation: SecretStr

    @model_validator(mode="after")
    def validate_confirmation(self):
        """임시 비밀번호 확인값이 일치하는지 검증한다."""
        if self.temporary_password.get_secret_value() != self.confirmation.get_secret_value():
            raise ValueError("비밀번호 확인이 일치하지 않습니다.")
        return self


class UserView(BaseModel):
    id: int
    login_id: str
    display_name: str
    email: str | None
    organization_id: int
    organization_name: str
    system_role: str
    is_active: bool
    must_change_password: bool
    created_at: datetime
    updated_at: datetime
    deactivated_at: datetime | None


class OrganizationView(BaseModel):
    id: int
    key: str
    name: str
    parent_id: int | None
    description: str
    is_active: bool
    selectable: bool
    depth: int
    member_count: int


class UserPage(BaseModel):
    users: list[UserView]
    total: int
    page: int
    page_size: int
