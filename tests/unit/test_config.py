from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import load_settings


def test_loads_external_config_and_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """설정 관련 동작을 검증한다."""
    config_file = tmp_path / "application.toml"
    config_file.write_text(
        "[audit]\nretention_days = 45\ncleanup_interval_hours = 24\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TTMS__AUDIT__RETENTION_DAYS", "60")

    settings = load_settings(str(config_file))

    assert settings.audit.retention_days == 60
    assert settings.audit.cleanup_interval_hours == 24


def test_default_config_file_is_read_from_top_level_config_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """설정 관련 동작을 검증한다."""
    config_directory = tmp_path / "config"
    config_directory.mkdir()
    (config_directory / "application.toml").write_text(
        "[server]\nport = 9123\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("APP_CONFIG_FILE", raising=False)

    settings = load_settings()

    assert settings.server.port == 9123


def test_log_level_can_be_overridden_by_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """환경 변수의 로그 레벨 override를 검증한다."""
    config_file = tmp_path / "application.toml"
    config_file.write_text("[app]\nlog_level = \"INFO\"\n", encoding="utf-8")
    monkeypatch.setenv("TTMS__APP__LOG_LEVEL", "DEBUG")

    settings = load_settings(str(config_file))

    assert settings.app.log_level == "DEBUG"


def test_rejects_unknown_config_key(tmp_path: Path) -> None:
    """설정 관련 동작을 검증한다."""
    config_file = tmp_path / "application.toml"
    config_file.write_text("[audit]\nunknown = true\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_settings(str(config_file))


def test_default_database_path_is_under_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DB 관련 동작을 검증한다."""
    monkeypatch.setenv("APP_DATA_ROOT", str(tmp_path))

    settings = load_settings(str(tmp_path / "missing.toml"))

    assert settings.database_directory == str(tmp_path / "database")
    assert settings.database_url.endswith("/database/task_tickets.db")
    assert settings.logs_directory == str(tmp_path / "logs")
    assert settings.log_file_path == str(tmp_path / "logs" / "application.log")


def test_logging_rotation_settings_can_be_overridden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """로깅 관련 동작을 검증한다."""
    monkeypatch.setenv("APP_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("TTMS__LOGGING__MAX_SIZE_MB", "25")
    monkeypatch.setenv("TTMS__LOGGING__BACKUP_COUNT", "3")
    monkeypatch.setenv("TTMS__LOGGING__FILE_NAME", "system.log")

    settings = load_settings(str(tmp_path / "missing.toml"))

    assert settings.logging.max_size_mb == 25
    assert settings.logging.backup_count == 3
    assert settings.log_file_path == str(tmp_path / "logs" / "system.log")
