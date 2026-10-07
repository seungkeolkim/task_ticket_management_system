#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CONFIG_FILE=${APP_CONFIG_FILE:-"$SCRIPT_DIR/config/application.toml"}
CONFIG_FILE_NAME=${CONFIG_FILE##*/}

if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    echo "compose_runner_error: Python 3 is required" >&2
    exit 1
fi

case "${1:-}" in
    start)
        CONFIG_FILE_DIR=$(CDPATH= cd -- "$(dirname -- "$CONFIG_FILE")" && pwd)
        APP_PORT=$(
            "$PYTHON_BIN" "$SCRIPT_DIR/scripts/read-compose-port.py" "$CONFIG_FILE"
        )
        COMPOSE_ACTION="up --build --detach"
        ;;
    stop)
        # docker compose down does not use the port, and must remain available
        # even when application.toml is temporarily invalid.
        APP_PORT=8000
        CONFIG_FILE_DIR="$SCRIPT_DIR/config"
        CONFIG_FILE_NAME=application.toml
        COMPOSE_ACTION="down"
        ;;
    *)
        echo "Usage: $0 {start|stop}" >&2
        exit 2
        ;;
esac

export APP_PORT
export HOST_CONFIG_DIR="$CONFIG_FILE_DIR"
export CONTAINER_CONFIG_FILE="/app/config/$CONFIG_FILE_NAME"

cd "$SCRIPT_DIR"
# COMPOSE_ACTION is restricted to the two constant values in the case above.
# shellcheck disable=SC2086
exec docker compose -f compose.yaml $COMPOSE_ACTION
