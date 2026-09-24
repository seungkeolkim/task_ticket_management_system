from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.domain.auth import Identity
from app.schemas.dashboard import DashboardView
from app.services import dashboard as service
from app.web.security import require_api_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
Database = Annotated[Session, Depends(get_db_session)]
Actor = Annotated[Identity, Depends(require_api_user)]


@router.get("", response_model=DashboardView)
def get_dashboard_api(session: Database, actor: Actor):
    return service.get_dashboard(session, actor)
