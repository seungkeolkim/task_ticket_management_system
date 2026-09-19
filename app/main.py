import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.api.router import api_router
from app.core.config import ensure_data_directories, get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.domain.auth import AuthError
from app.services.bootstrap import bootstrap_from_environment
from app.web.administration import router as administration_router
from app.web.auth import router as auth_router
from app.web.projects import router as projects_router
from app.web.router import STATIC_DIRECTORY
from app.web.router import router as web_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    ensure_data_directories(settings)
    configure_logging(
        settings.app.log_level,
        log_file=settings.log_file_path if settings.logging.file_enabled else None,
        max_bytes=settings.logging.max_size_mb * 1024 * 1024,
        backup_count=settings.logging.backup_count,
    )
    try:
        await run_in_threadpool(
            bootstrap_from_environment, application.state.session_factory, settings
        )
    except Exception:
        logger.exception("auth_bootstrap_failed")
        raise
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
    application.state.session_factory = SessionLocal

    @application.exception_handler(AuthError)
    async def auth_error_handler(_: Request, error: AuthError) -> JSONResponse:
        headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
        return JSONResponse(
            {"code": error.code, "message": error.message},
            status_code=error.status_code,
            headers=headers,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, error: RequestValidationError) -> JSONResponse:
        # Default Pydantic errors may contain submitted passwords and tokens.
        return JSONResponse(
            {"code": "invalid_request", "message": "입력 항목을 확인하세요."}, status_code=422
        )

    @application.middleware("http")
    async def private_page_headers(request: Request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith(("/static/", "/health")):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    application.mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static")
    application.include_router(auth_router)
    application.include_router(administration_router)
    application.include_router(projects_router)
    application.include_router(web_router)
    application.include_router(api_router)
    return application


app = create_app()
