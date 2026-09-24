import uvicorn

from app.core.config import ensure_data_directories, get_settings
from app.core.logging import configure_logging


def main() -> None:
    """명령행 진입점을 실행한다."""
    settings = get_settings()
    ensure_data_directories(settings)
    configure_logging(
        settings.app.log_level,
        log_file=settings.log_file_path if settings.logging.file_enabled else None,
        max_bytes=settings.logging.max_size_mb * 1024 * 1024,
        backup_count=settings.logging.backup_count,
    )
    uvicorn.run(
        "app.main:app",
        host=settings.server.host,
        port=settings.server.port,
        workers=settings.server.workers,
        reload=False,
        log_level=settings.app.log_level.lower(),
        log_config=None,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
