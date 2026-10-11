"""조회와 저장에서 동일하게 사용하는 조건 트리 참조 검증이다."""

from sqlalchemy.orm import Session

from app.domain.auth import AuthError
from app.repositories import tickets as ticket_repository
from app.schemas.ticket_filters import TicketFilter, iter_filter_conditions


def validate_saved_filter_definition(
    session: Session, project_id: int, definition: TicketFilter
) -> None:
    """중첩·부정 여부와 무관하게 모든 사용자·계층 참조를 현재 프로젝트에서 검사한다."""
    conditions = list(iter_filter_conditions(definition.expression))
    hierarchy_conditions = [
        condition
        for condition in conditions
        if condition.field in {"epic", "parent"} and condition.values
    ]
    if hierarchy_conditions:
        hierarchy = {
            candidate["id"]: candidate["type"]
            for candidate in ticket_repository.ticket_filter_hierarchy(session, project_id)
        }
        for condition in hierarchy_conditions:
            for identifier in condition.values:
                valid_type = hierarchy.get(identifier)
                if valid_type is None or (condition.field == "epic" and valid_type != "EPIC"):
                    raise AuthError("invalid_filter_reference", "상위 티켓 조건을 다시 선택하세요.")
    user_conditions = [
        condition
        for condition in conditions
        if condition.field in {"creator", "assignee"}
        and condition.rule is None
        and condition.values
    ]
    if user_conditions:
        valid_user_ids = {
            candidate["id"]
            for candidate in ticket_repository.ticket_filter_users(session, project_id)
        }
        for condition in user_conditions:
            if not set(condition.values).issubset(valid_user_ids):
                raise AuthError("invalid_filter_reference", "생성자·담당자 조건을 다시 선택하세요.")
