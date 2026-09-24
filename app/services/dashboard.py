from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.domain.auth import Identity
from app.repositories import dashboard as repository
from app.schemas.dashboard import DashboardCounts, DashboardView, MentionView
from app.services import projects as project_service
from app.services.tickets import build_ticket_view

SEOUL = ZoneInfo("Asia/Seoul")


def get_local_today():
    """로컬 today 정보를 조회한다."""
    return datetime.now(SEOUL).date()


def get_dashboard(session: Session, actor: Identity) -> DashboardView:
    """대시보드 정보를 조회한다."""
    today = get_local_today()
    week_end = today + timedelta(days=6 - today.weekday())
    with project_service.project_operation_context(session, actor, "dashboard_read"):
        project_service.is_system_administrator(session, actor)
        dashboard_count_row = repository.get_dashboard_counts(session, actor.id, today, week_end)
        return DashboardView(
            today=today,
            week_end=week_end,
            counts=DashboardCounts(**dashboard_count_row._mapping),
            recent_tickets=[
                build_ticket_view(ticket_row)
                for ticket_row in repository.list_recent_tickets(session, actor.id)
            ],
            mentions=[
                MentionView(**{**mention_row, "excerpt": (mention_row["excerpt"] or "")[:160]})
                for mention_row in repository.list_unread_mentions(session, actor.id)
            ],
        )
