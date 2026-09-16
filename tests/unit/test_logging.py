from __future__ import annotations

import io
import logging
import re

from app.core.logging import configure_logging


def test_configure_logging_uses_requested_level_and_time_first_format() -> None:
    output = io.StringIO()
    configure_logging("WARNING", stream=output)

    logger = logging.getLogger("tests.logging")
    logger.info("not_emitted")
    logger.warning("example_event ticket_id=%s", 42)

    line = output.getvalue().strip()
    assert "not_emitted" not in line
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z "
        r"WARNING tests\.logging example_event ticket_id=42",
        line,
    )


def test_configure_logging_routes_framework_loggers_through_root() -> None:
    output = io.StringIO()
    configure_logging("INFO", stream=output)

    logging.getLogger("uvicorn.error").info("server_event")
    logging.getLogger("alembic").info("migration_event")

    lines = output.getvalue().splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("INFO uvicorn.error server_event")
    assert lines[1].endswith("INFO alembic migration_event")


def test_configure_logging_writes_and_rotates_file(tmp_path) -> None:
    output = io.StringIO()
    log_file = tmp_path / "logs" / "application.log"
    configure_logging(
        "INFO",
        stream=output,
        log_file=str(log_file),
        max_bytes=80,
        backup_count=2,
    )

    logger = logging.getLogger("tests.rotation")
    for index in range(5):
        logger.info("rotation_event index=%s payload=%s", index, "x" * 40)

    for handler in logging.getLogger().handlers:
        handler.flush()

    assert log_file.exists()
    assert (tmp_path / "logs" / "application.log.1").exists()
    assert len(list((tmp_path / "logs").glob("application.log*"))) <= 3
