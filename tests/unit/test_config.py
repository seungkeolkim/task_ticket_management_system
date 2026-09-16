from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import load_settings


def test_loads_external_config_and_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file = tmp_path / "application.toml"
    config_file.write_text(
        "[audit]\nretention_days = 45\ncleanup_interval_hours = 24\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TTMS__AUDIT__RETENTION_DAYS", "60")

    settings = load_settings(str(config_file))

    assert settings.audit.retention_days == 60
    assert settings.audit.cleanup_interval_hours == 24


def test_rejects_unknown_config_key(tmp_path: Path) -> None:
    config_file = tmp_path / "application.toml"
    config_file.write_text("[audit]\nunknown = true\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_settings(str(config_file))


def test_default_database_path_is_under_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_DATA_ROOT", str(tmp_path))

    settings = load_settings(str(tmp_path / "missing.toml"))

    assert settings.database_directory == str(tmp_path / "database")
    assert settings.database_url.endswith("/database/task_tickets.db")

