"""Shared creation inputs and explicit public DTOs for administrator screens."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


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
        if not value:
            return None
        value = value.lower()
        if (
            value.count("@") != 1
            or any(char.isspace() or ord(char) < 32 for char in value)
            or not all(value.split("@"))
        ):
            raise ValueError("이메일 형식을 확인하세요.")
        return value


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
