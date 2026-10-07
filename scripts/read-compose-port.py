from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

DEFAULT_SERVER_PORT = 8000


def read_server_port(config_file: Path) -> int:
    """외부 설정과 환경 변수의 server port를 읽고 검증한다."""
    try:
        with config_file.open("rb") as file_handle:
            settings: dict[str, Any] = tomllib.load(file_handle)
    except FileNotFoundError:
        settings = {}
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML configuration: {config_file}: {exc}") from exc

    server = settings.get("server", {})
    if not isinstance(server, dict):
        raise ValueError("server must be a table")

    port = server.get("port", DEFAULT_SERVER_PORT)
    environment_port = os.getenv("TTMS__SERVER__PORT")
    if environment_port is not None:
        try:
            port = json.loads(environment_port)
        except json.JSONDecodeError as exc:
            raise ValueError("server.port must be an integer between 1 and 65535") from exc
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
