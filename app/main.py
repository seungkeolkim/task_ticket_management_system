import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import ensure_data_directories, get_settings
from app.core.logging import configure_logging
from app.web.router import STATIC_DIRECTORY
from app.web.router import router as web_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    ensure_data_directories(settings)
    configure_logging(
        settings.app.log_level,
        log_file=settings.log_file_path if settings.logging.file_enabled else None,
        max_bytes=settings.logging.max_size_mb * 1024 * 1024,
        backup_count=settings.logging.backup_count,
    )
    logger.info(
        "application_started environment=%s log_level=%s",
        settings.app.environment,
        settings.app.log_level,
    )
    yield
    logger.info("application_stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app.name,
        debug=settings.app.debug,
        version="0.1.0",
        lifespan=lifespan,
    )
    application.mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static")
    application.include_router(web_router)
    application.include_router(api_router)
    return application


app = create_app()
