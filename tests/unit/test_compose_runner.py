from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_port_reader():
    """Compose 포트 판독 script를 테스트용으로 불러온다."""
    script_path = Path("scripts") / "read-compose-port.py"
    spec = importlib.util.spec_from_file_location("read_compose_port", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compose_port_reader_reads_server_port(tmp_path: Path) -> None:
    """Compose 관련 동작을 검증한다."""
    config_file = tmp_path / "application.toml"
    config_file.write_text("[server]\nport = 9123\n", encoding="utf-8")

    module = _load_port_reader()

    assert module.read_server_port(config_file) == 9123


def test_compose_port_reader_uses_defaults_without_file_or_port(tmp_path: Path) -> None:
    """설정 파일이나 port 항목이 없을 때 기본 포트를 사용한다."""
    module = _load_port_reader()
    config_file = tmp_path / "application.toml"

    assert module.read_server_port(config_file) == 8000
    config_file.write_text("[app]\nname = 'Example'\n", encoding="utf-8")
    assert module.read_server_port(config_file) == 8000


def test_compose_port_reader_applies_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """환경 변수 포트가 TOML 값보다 우선하는지 확인한다."""
    config_file = tmp_path / "application.toml"
    config_file.write_text("[server]\nport = 9123\n", encoding="utf-8")
    monkeypatch.setenv("TTMS__SERVER__PORT", "9234")

    assert _load_port_reader().read_server_port(config_file) == 9234


@pytest.mark.parametrize("value", ["0", "65536", '"8000"', "true"])
def test_compose_port_reader_rejects_invalid_port(tmp_path: Path, value: str) -> None:
    """Compose 관련 동작을 검증한다."""
    config_file = tmp_path / "application.toml"
    config_file.write_text(f"[server]\nport = {value}\n", encoding="utf-8")

    module = _load_port_reader()

    with pytest.raises(ValueError, match="server.port"):
        module.read_server_port(config_file)
