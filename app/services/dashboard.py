from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.domain.auth import Identity
from app.repositories import dashboard as repository
from app.schemas.dashboard import DashboardCounts, DashboardView, MentionView
from app.services import projects as project_service
from app.services.tickets import view

SEOUL = ZoneInfo("Asia/Seoul")


def local_today():
    return datetime.now(SEOUL).date()


def dashboard(session: Session, actor: Identity) -> DashboardView:
    today = local_today()
    week_end = today + timedelta(days=6 - today.weekday())
    with project_service.operation(session, actor, "dashboard_read"):
        project_service.actor_is_admin(session, actor)
        count_row = repository.counts(session, actor.id, today, week_end)
        return DashboardView(
            today=today,
            week_end=week_end,
            counts=DashboardCounts(**count_row._mapping),
            recent_tickets=[view(row) for row in repository.recent_tickets(session, actor.id)],
            mentions=[
                MentionView(
                    **{
                        **row,
                        "excerpt": (row["excerpt"] or "")[:160],
                    }
                )
                for row in repository.unread_mentions(session, actor.id)
            ],
        )
