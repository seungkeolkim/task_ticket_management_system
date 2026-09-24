from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import Any


def read_server_port(config_file: Path) -> int:
    """TOML 설정에서 server port를 읽고 검증한다."""
    try:
        with config_file.open("rb") as file_handle:
            settings: dict[str, Any] = tomllib.load(file_handle)
    except FileNotFoundError as exc:
        raise ValueError(f"Configuration file does not exist: {config_file}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML configuration: {config_file}: {exc}") from exc

    server = settings.get("server")
    if not isinstance(server, dict):
        raise ValueError("Configuration must contain a [server] table")

    port = server.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("server.port must be an integer between 1 and 65535")
    return port


def main() -> int:
    """명령행 진입점을 실행한다."""
    if len(sys.argv) != 2:
        print("Usage: read-compose-port.py <application.toml>", file=sys.stderr)
        return 2

    try:
        port = read_server_port(Path(sys.argv[1]))
    except (OSError, ValueError) as exc:
        print(f"compose_config_error: {exc}", file=sys.stderr)
        return 2

    print(port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
