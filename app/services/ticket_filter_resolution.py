"""동적 규칙을 요청당 한 번 해석하고 저장용 원본 조건은 보존한다."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.db.types import utc_now
from app.domain.auth import AuthError, Identity
from app.schemas.ticket_filters import (
    CurrentUserRule,
    DayOffsetRule,
    FilterCondition,
    FilterGroup,
    FilterResolution,
    RelativePeriodRule,
    ResolvedFilterCondition,
    TicketFilter,
    WorkingWeekRule,
)


def resolve_ticket_filter(
    definition: TicketFilter, actor: Identity, *, evaluated_at: datetime | None = None
) -> tuple[TicketFilter, FilterResolution]:
    """한국 날짜·인증된 사용자를 고정하고 조회용 복사본과 해석 정보를 반환한다."""
    reference_timestamp = evaluated_at if evaluated_at is not None else utc_now()
    if reference_timestamp.tzinfo is None or reference_timestamp.utcoffset() is None:
        raise ValueError("기준 시각은 timezone-aware datetime이어야 합니다.")
    reference_date = reference_timestamp.astimezone(ZoneInfo("Asia/Seoul")).date()
    resolved_definition = definition.model_copy(deep=True)
    resolution = FilterResolution(
        evaluated_at=reference_timestamp,
        reference_date=reference_date,
        user_id=actor.id,
        user_label=f"{actor.display_name} · {actor.login_id}",
    )

    def resolve_group(group: FilterGroup, path: str) -> None:
        """그룹 순서와 NOT을 유지하면서 하위 동적 조건만 고정값으로 바꾼다."""
        for child_index, child in enumerate(group.children):
            child_path = f"{path}.{child_index}"
            if isinstance(child, FilterGroup):
                resolve_group(child, child_path)
                continue
            if child.rule is None:
                continue
            rule = child.rule
            if isinstance(rule, CurrentUserRule):
                resolved_values = [actor.id]
            else:
                first_date = reference_date
                last_date = reference_date
                if isinstance(rule, DayOffsetRule):
                    offset = -rule.days if rule.direction == "past" else rule.days
                    first_date = reference_date + timedelta(days=offset)
                    last_date = first_date
                elif isinstance(rule, RelativePeriodRule):
                    if rule.direction == "past":
                        first_date -= timedelta(days=rule.days - 1)
                    else:
                        last_date += timedelta(days=rule.days - 1)
                elif isinstance(rule, WorkingWeekRule):
                    first_date -= timedelta(days=reference_date.weekday())
                    if rule.week == "last":
                        first_date -= timedelta(days=7)
                    last_date = first_date + timedelta(days=4)
                resolved_values = [first_date.isoformat()]
                if child.operator == "between":
                    resolved_values.append(last_date.isoformat())
            condition_payload = child.model_dump() | {"values": resolved_values, "rule": None}
            resolved_child = FilterCondition.model_validate(condition_payload)
            group.children[child_index] = resolved_child
            resolution.conditions.append(
                ResolvedFilterCondition(path=child_path, field=child.field, values=resolved_values)
            )

    try:
        resolve_group(resolved_definition.expression, "expression")
    except (OverflowError, ValueError):
        raise AuthError("invalid_filter", "동적 날짜의 범위를 확인하세요.") from None
    return resolved_definition, resolution
