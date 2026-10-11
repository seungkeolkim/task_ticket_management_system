"""검증된 조건 트리를 DB 중립적인 SQLAlchemy 조건으로 변환한다."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, false, func, not_, or_, select, true

from app.models import Ticket
from app.schemas.ticket_filters import FilterCondition, FilterGroup


def build_filter_expression(expression: FilterGroup, project_id: int):
    """권한 조건과 별도로 조건 트리의 참·거짓 SQL 표현식을 만든다."""
    child_expressions = []
    for child_node in expression.children:
        if isinstance(child_node, FilterGroup):
            child_expression = build_filter_expression(child_node, project_id)
        else:
            child_expression = build_condition_expression(child_node, project_id)
        child_expressions.append(child_expression)
    if not child_expressions:
        combined_expression = true()
    elif expression.operator == "AND":
        combined_expression = and_(*child_expressions)
    else:
        combined_expression = or_(*child_expressions)
    return not_(combined_expression) if expression.negated else combined_expression


def build_condition_expression(condition: FilterCondition, project_id: int):
    """허용된 필드만 조회하고 NULL도 두 값 논리로 판정한 뒤 부정한다."""
    field_columns = {
        "type": Ticket.type,
        "status": Ticket.status,
        "priority": Ticket.priority,
        "parent": Ticket.parent_id,
        "creator": Ticket.creator_id,
        "assignee": Ticket.assignee_id,
        "created_date": Ticket.created_at,
        "updated_date": Ticket.updated_at,
        "due_date": Ticket.due_date,
    }
    operator = condition.operator
    if condition.field == "search":
        positive_expression = or_(
            Ticket.key.icontains(condition.values[0], autoescape=True),
            Ticket.title.icontains(condition.values[0], autoescape=True),
        )
    elif condition.field == "epic":
        positive_expression = build_epic_expression(condition.values, project_id)
    else:
        field_column = field_columns[condition.field]
        if operator == "is_empty":
            positive_expression = field_column.is_(None)
        elif operator == "is_not_empty":
            positive_expression = field_column.is_not(None)
        elif condition.field in {"created_date", "updated_date", "due_date"}:
            positive_expression = build_date_expression(field_column, condition)
        else:
            positive_expression = field_column.in_(condition.values)
    # SQL NULL의 UNKNOWN을 거짓으로 바꿔 NOT에서도 미지정 티켓을 보존한다.
    boolean_expression = func.coalesce(positive_expression, false())
    is_negative = operator in {"not_in", "not_contains"}
    if is_negative != condition.negated:
        return not_(boolean_expression)
    return boolean_expression


def build_epic_expression(epic_identifiers: list, project_id: int):
    """Epic 자체와 해당 Epic 아래의 Task·Subtask를 같은 프로젝트에서 조회한다."""
    selected_epics = select(Ticket.id).where(
        Ticket.project_id == project_id,
        Ticket.type == "EPIC",
        Ticket.deleted_at.is_(None),
        Ticket.id.in_(epic_identifiers),
    )
    selected_tasks = select(Ticket.id).where(
        Ticket.project_id == project_id,
        Ticket.type == "TASK",
        Ticket.deleted_at.is_(None),
        Ticket.parent_id.in_(selected_epics),
    )
    return or_(
        Ticket.id.in_(selected_epics),
        Ticket.parent_id.in_(selected_epics),
        and_(Ticket.type == "SUBTASK", Ticket.parent_id.in_(selected_tasks)),
    )


def build_date_expression(field_column, condition: FilterCondition):
    """한국 날짜 전체를 포함하고 이전·이후는 선택 날짜를 제외한다."""
    first_date = date.fromisoformat(condition.values[0])
    last_date = date.fromisoformat(condition.values[-1])
    if condition.field == "due_date":
        if condition.operator == "before":
            return field_column < first_date
        if condition.operator == "after":
            return field_column > first_date
        return field_column.between(first_date, last_date)
    timezone = ZoneInfo("Asia/Seoul")
    start_timestamp = datetime.combine(first_date, time.min, tzinfo=timezone)
    end_timestamp = datetime.combine(last_date + timedelta(days=1), time.min, tzinfo=timezone)
    if condition.operator == "before":
        return field_column < start_timestamp
    if condition.operator == "after":
        return field_column >= end_timestamp
    return and_(field_column >= start_timestamp, field_column < end_timestamp)
