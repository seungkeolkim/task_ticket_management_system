import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from typing import TextIO


class UTCFormatter(logging.Formatter):
    converter = time.gmtime


def configure_logging(
    log_level: str,
    *,
    log_file: str | None = None,
    max_bytes: int = 100 * 1024 * 1024,
    backup_count: int = 10,
    stream: TextIO | None = None,
) -> None:
    """Configure console and optional rotating-file logs with one format."""
    level = getattr(logging, log_level.upper())
    formatter = UTCFormatter(
        fmt="%(asctime)s.%(msecs)03dZ %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    console_handler = logging.StreamHandler(stream or sys.stdout)
    console_handler.setFormatter(formatter)
    handlers: list[logging.Handler] = [console_handler]

    if log_file is not None:
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    root_logger = logging.getLogger()
    previous_handlers = list(root_logger.handlers)
    root_logger.handlers.clear()
    for handler in handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(level)
    for previous_handler in previous_handlers:
        previous_handler.close()

    # Uvicorn normally installs separate handlers. Route its logs through the
    # same root handler so direct execution has one format and one level.
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "alembic"):
        server_logger = logging.getLogger(logger_name)
        server_logger.disabled = False
        server_logger.handlers.clear()
        server_logger.setLevel(level)
        server_logger.propagate = True
