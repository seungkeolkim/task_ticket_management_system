from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import ensure_data_directories, get_settings
from app.core.logging import configure_logging
from app.web.router import STATIC_DIRECTORY
from app.web.router import router as web_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.app.log_level)
    ensure_data_directories(settings)
    yield


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
