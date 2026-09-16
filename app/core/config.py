from __future__ import annotations

import json
import os
import tomllib
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ENVIRONMENT_PREFIX = "TTMS__"


class StrictSettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApplicationSettings(StrictSettingsModel):
    name: str = "Task Ticket Management System"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    timezone: str = "Asia/Seoul"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"


class ServerSettings(StrictSettingsModel):
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    workers: int = Field(default=1, ge=1)


class StorageSettings(StrictSettingsModel):
    data_root: str = "./data"
    database_dir: str = "database"
    attachments_dir: str = "attachments"
    backups_dir: str = "backups"
    logs_dir: str = "logs"


class LoggingSettings(StrictSettingsModel):
    file_enabled: bool = True
    file_name: str = Field(default="application.log", min_length=1)
    max_size_mb: int = Field(default=100, gt=0)
    backup_count: int = Field(default=10, ge=1)

    @model_validator(mode="after")
    def validate_file_name(self) -> LoggingSettings:
        if os.path.basename(self.file_name) != self.file_name:
            raise ValueError("logging.file_name must be a file name without a path")
        return self


class DatabaseSettings(StrictSettingsModel):
    url: str | None = None
    echo: bool = False
    pool_pre_ping: bool = True


class AttachmentSettings(StrictSettingsModel):
    max_file_size_mb: int = Field(default=25, gt=0)
    deleted_file_retention_days: int = Field(default=30, ge=0)
    allowed_extensions: list[str] = Field(default_factory=list)
    blocked_extensions: list[str] = Field(default_factory=list)


class AuditSettings(StrictSettingsModel):
    retention_days: int = Field(default=30, ge=1)
    cleanup_interval_hours: int = Field(default=24, ge=1)


class TicketTrashSettings(StrictSettingsModel):
    retention_days: int = Field(default=30, ge=1)
    cleanup_interval_hours: int = Field(default=24, ge=1)


class SessionSettings(StrictSettingsModel):
    lifetime_minutes: int = Field(default=480, ge=1)
    cookie_name: str = "ttms_session"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"


class PaginationSettings(StrictSettingsModel):
    default_size: int = 20
    allowed_sizes: list[int] = Field(default_factory=lambda: [10, 20, 50])

    @model_validator(mode="after")
    def validate_default_size(self) -> PaginationSettings:
        if not self.allowed_sizes:
            raise ValueError("pagination.allowed_sizes must not be empty")
        if self.default_size not in self.allowed_sizes:
            raise ValueError("pagination.default_size must be one of allowed_sizes")
        if any(size <= 0 for size in self.allowed_sizes):
            raise ValueError("pagination.allowed_sizes must contain only positive values")
        return self


class BackupSettings(StrictSettingsModel):
    retention_days: int = Field(default=30, ge=1)
    max_archives: int = Field(default=10, ge=1)


class Settings(StrictSettingsModel):
    app: ApplicationSettings = Field(default_factory=ApplicationSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    attachments: AttachmentSettings = Field(default_factory=AttachmentSettings)
    audit: AuditSettings = Field(default_factory=AuditSettings)
    ticket_trash: TicketTrashSettings = Field(default_factory=TicketTrashSettings)
    session: SessionSettings = Field(default_factory=SessionSettings)
    pagination: PaginationSettings = Field(default_factory=PaginationSettings)
    backup: BackupSettings = Field(default_factory=BackupSettings)

    @property
    def database_directory(self) -> str:
        return os.path.abspath(
            os.path.join(self.storage.data_root, self.storage.database_dir)
        )

    @property
    def attachments_directory(self) -> str:
        return os.path.abspath(
            os.path.join(self.storage.data_root, self.storage.attachments_dir)
        )

    @property
    def backups_directory(self) -> str:
        return os.path.abspath(os.path.join(self.storage.data_root, self.storage.backups_dir))

    @property
    def logs_directory(self) -> str:
        return os.path.abspath(os.path.join(self.storage.data_root, self.storage.logs_dir))

    @property
    def log_file_path(self) -> str:
        return os.path.join(self.logs_directory, self.logging.file_name)

    @property
    def database_url(self) -> str:
        if self.database.url:
            return self.database.url
        database_path = os.path.join(self.database_directory, "task_tickets.db")
        normalized_path = database_path.replace("\\", "/")
        return f"sqlite:///{normalized_path}"


def _read_toml(config_file: str) -> dict[str, Any]:
    if not os.path.exists(config_file):
        return {}
    if not os.path.isfile(config_file):
        raise ValueError(f"Configuration path is not a file: {config_file}")
    try:
        with open(config_file, "rb") as file_handle:
            return tomllib.load(file_handle)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML configuration: {config_file}: {exc}") from exc


def _parse_environment_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _set_nested_value(target: dict[str, Any], path: list[str], value: Any) -> None:
    current = target
    for part in path[:-1]:
        existing = current.setdefault(part, {})
        if not isinstance(existing, dict):
            raise ValueError(f"Environment setting collides with a scalar value: {part}")
        current = existing
    current[path[-1]] = value


def _environment_overrides() -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for key, value in os.environ.items():
        normalized_key = key.upper()
        if not normalized_key.startswith(ENVIRONMENT_PREFIX):
            continue
        setting_path = normalized_key[len(ENVIRONMENT_PREFIX) :].lower().split("__")
        if not all(setting_path):
            raise ValueError(f"Invalid nested setting environment variable: {key}")
        _set_nested_value(overrides, setting_path, _parse_environment_value(value))

    if data_root := os.getenv("APP_DATA_ROOT"):
        _set_nested_value(overrides, ["storage", "data_root"], data_root)
    if database_url := os.getenv("DATABASE_URL"):
        _set_nested_value(overrides, ["database", "url"], database_url)
    return overrides


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(config_file: str | None = None) -> Settings:
    data_root = os.getenv("APP_DATA_ROOT", "./data")
    resolved_config_file = config_file or os.getenv("APP_CONFIG_FILE") or os.path.join(
        data_root, "config", "application.toml"
    )
    file_settings = _read_toml(resolved_config_file)
    merged_settings = _deep_merge(file_settings, _environment_overrides())
    return Settings.model_validate(merged_settings)


@lru_cache
def get_settings() -> Settings:
    return load_settings()


def ensure_data_directories(settings: Settings) -> None:
    for directory in (
        settings.database_directory,
        settings.attachments_directory,
        settings.backups_directory,
        settings.logs_directory,
    ):
        os.makedirs(directory, exist_ok=True)
