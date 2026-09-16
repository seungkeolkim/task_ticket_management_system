from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session

router = APIRouter(tags=["system"])


@router.get("/")
def root() -> dict[str, str]:
    settings = get_settings()
    return {"name": settings.app.name, "status": "running"}


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(session: Annotated[Session, Depends(get_db_session)]) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ready", "database": "ok"}

