from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.tickets import TicketView


class DashboardCounts(BaseModel):
    open_mine: int
    overdue: int
    due_this_week: int


class MentionView(BaseModel):
    id: int
    project_key: str
    project_name: str
    ticket_key: str
    actor_display_name: str
    excerpt: str
    created_at: datetime
    comment_id: int | None


class DashboardView(BaseModel):
    today: date
    week_end: date
    counts: DashboardCounts
    recent_tickets: list[TicketView] = Field(default_factory=list)
    mentions: list[MentionView] = Field(default_factory=list)
