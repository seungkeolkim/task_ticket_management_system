from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db_session

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    """애플리케이션 health 상태를 반환한다."""
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(session: Annotated[Session, Depends(get_db_session)]) -> dict[str, str]:
    """DB 연결을 포함한 readiness 상태를 반환한다."""
    session.execute(text("SELECT 1"))
    return {"status": "ready", "database": "ok"}
