from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.domain.auth import AuthError
from app.repositories import tickets as ticket_repository
from app.schemas.contracts import TicketFilter


def validate_saved_filter_definition(
    session: Session, project_id: int, definition: TicketFilter
) -> None:
    """계층·사용자 참조와 날짜 경계를 현재 프로젝트의 선택 가능 범위로 제한한다."""
    hierarchy = {
        candidate["id"]: candidate["type"]
        for candidate in ticket_repository.ticket_filter_hierarchy(session, project_id)
    }
    if definition.epic_id is not None and hierarchy.get(definition.epic_id) != "EPIC":
        raise AuthError("invalid_filter_reference", "Epic 조건을 다시 선택하세요.")
    if definition.parent_id is not None and definition.parent_id not in hierarchy:
        raise AuthError("invalid_filter_reference", "상위 티켓 조건을 다시 선택하세요.")
    valid_user_ids = {
        candidate["id"] for candidate in ticket_repository.ticket_filter_users(session, project_id)
    }
    if not set(definition.creator_ids + definition.assignee_ids).issubset(valid_user_ids):
        raise AuthError("invalid_filter_reference", "생성자·담당자 조건을 다시 선택하세요.")
    for timestamp in (
        definition.created_from,
        definition.created_before,
        definition.updated_from,
        definition.updated_before,
    ):
        if timestamp is None:
            continue
        try:
            local_timestamp = timestamp.astimezone(ZoneInfo("Asia/Seoul"))
            if timestamp in (definition.created_before, definition.updated_before):
                local_timestamp.date() - timedelta(days=1)
        except (OverflowError, ValueError):
            raise AuthError("invalid_filter_date", "저장할 날짜 범위를 확인하세요.") from None
        if any(
            (
                local_timestamp.hour,
                local_timestamp.minute,
                local_timestamp.second,
                local_timestamp.microsecond,
            )
        ):
            raise AuthError(
                "invalid_filter_date", "날짜 조건은 한국 날짜의 시작을 기준으로 저장하세요."
            )
