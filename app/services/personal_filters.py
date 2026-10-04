import logging
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.domain.auth import AuthError, Identity
from app.models import AuditLog, SavedFilter
from app.repositories import personal_filters as repository
from app.repositories import projects as project_repository
from app.schemas.contracts import TicketFilter
from app.schemas.personal_filters import (
    PersonalFilterCreate,
    PersonalFilterDelete,
    PersonalFilterSummary,
    PersonalFilterUpdate,
    PersonalFilterView,
)
from app.services import projects as project_service
from app.services.saved_filter_definitions import validate_saved_filter_definition

logger = logging.getLogger(__name__)


def personal_filter_summary(saved_filter: SavedFilter) -> PersonalFilterSummary:
    """ORM row를 개인 필터 요약으로 변환한다."""
    return PersonalFilterSummary(
        id=saved_filter.id, name=saved_filter.name, updated_at=saved_filter.updated_at
    )


def require_personal_filter(session, project_id, actor_id, filter_id) -> SavedFilter:
    """본인 필터만 반환하며 다른 범위의 필터 존재 여부를 은폐한다."""
    saved_filter = repository.get_personal_filter(session, project_id, actor_id, filter_id)
    if saved_filter is None:
        raise AuthError("personal_filter_not_found", "개인 필터를 찾을 수 없습니다.", 404)
    return saved_filter


def validate_unique_name(session, project_id, actor_id, name, excluded_id=None) -> None:
    """쓰기 잠금 안에서 같은 소유 범위의 이름 중복을 차단한다."""
    if repository.personal_filter_name_exists(session, project_id, actor_id, name, excluded_id):
        raise AuthError("personal_filter_name_conflict", "같은 이름의 개인 필터가 있습니다.", 409)


def record_personal_filter_audit(session, actor_id, saved_filter, action) -> None:
    """개인 검색 내용 없이 필터 식별자와 변경 종류만 감사 기록한다."""
    session.add(
        AuditLog(
            action=action,
            actor_user_id=actor_id,
            target_type="saved_filter",
            target_id=str(saved_filter.id),
            details={"project_id": saved_filter.project_id},
        )
    )


def list_personal_filters(session: Session, actor: Identity, project_key: str):
    """현재 프로젝트 접근 권한과 필터 소유 범위를 적용해 목록을 반환한다."""
    with project_service.project_operation_context(session, actor, "personal_filter_list"):
        project = project_service.require_project_member(session, actor, project_key)
        return [
            personal_filter_summary(saved_filter)
            for saved_filter in repository.list_personal_filters(session, project.id, actor.id)
        ]


def get_personal_filter(session: Session, actor: Identity, project_key: str, filter_id: int):
    """불러올 때마다 소유자·프로젝트 권한·저장 schema·참조를 다시 검사한다."""
    with project_service.project_operation_context(session, actor, "personal_filter_read"):
        project = project_service.require_project_member(session, actor, project_key)
        saved_filter = require_personal_filter(session, project.id, actor.id, filter_id)
        try:
            if saved_filter.schema_version != 1:
                raise ValueError("unsupported schema")
            definition = TicketFilter.model_validate(saved_filter.definition)
            validate_saved_filter_definition(session, project.id, definition)
        except (ValidationError, ValueError, AuthError):
            raise AuthError(
                "saved_filter_invalid",
                "저장된 조건을 사용할 수 없습니다. 현재 조건으로 덮어쓰거나 삭제하세요.",
                409,
            ) from None
        return PersonalFilterView(
            **personal_filter_summary(saved_filter).model_dump(), definition=definition
        )


def create_personal_filter(
    session: Session, actor: Identity, project_key: str, payload: PersonalFilterCreate
):
    """본인 전용 필터와 감사 기록을 한 transaction으로 생성한다."""
    with project_service.project_operation_context(
        session, actor, "personal_filter_create", write_operation=True
    ):
        project = project_service.require_project_member(session, actor, project_key)
        project_repository.lock_project_management(session, project.id)
        validate_unique_name(session, project.id, actor.id, payload.name)
        validate_saved_filter_definition(session, project.id, payload.definition)
        saved_filter = SavedFilter(
            project_id=project.id,
            owner_id=actor.id,
            name=payload.name,
            visibility="PERSONAL",
            schema_version=1,
            definition=payload.definition.model_dump(mode="json"),
        )
        session.add(saved_filter)
        session.flush()
        record_personal_filter_audit(session, actor.id, saved_filter, "personal_filter.created")
        result = personal_filter_summary(saved_filter)
    logger.info("personal_filter_created actor_id=%s filter_id=%s", actor.id, result.id)
    return result


def update_personal_filter(
    session: Session,
    actor: Identity,
    project_key: str,
    filter_id: int,
    payload: PersonalFilterUpdate,
):
    """동시 수정과 이름 중복을 차단하며 이름 또는 조건을 변경한다."""
    with project_service.project_operation_context(
        session, actor, "personal_filter_update", write_operation=True
    ):
        project = project_service.require_project_member(session, actor, project_key)
        project_repository.lock_project_management(session, project.id)
        saved_filter = require_personal_filter(session, project.id, actor.id, filter_id)
        require_current_filter_revision(saved_filter, payload.expected_updated_at)
        name = payload.name if payload.name is not None else saved_filter.name
        validate_unique_name(session, project.id, actor.id, name, filter_id)
        definition = saved_filter.definition
        if payload.definition is not None:
            validate_saved_filter_definition(session, project.id, payload.definition)
            definition = payload.definition.model_dump(mode="json")
        if (
            name == saved_filter.name
            and definition == saved_filter.definition
            and (payload.definition is None or saved_filter.schema_version == 1)
        ):
            return personal_filter_summary(saved_filter)
        saved_filter.name = name
        saved_filter.definition = definition
        if payload.definition is not None:
            saved_filter.schema_version = 1
        saved_filter.updated_at = max(
            datetime.now(UTC), saved_filter.updated_at + timedelta(microseconds=1)
        )
        session.flush()
        record_personal_filter_audit(session, actor.id, saved_filter, "personal_filter.updated")
        result = personal_filter_summary(saved_filter)
    logger.info("personal_filter_updated actor_id=%s filter_id=%s", actor.id, filter_id)
    return result


def require_current_filter_revision(saved_filter: SavedFilter, expected_updated_at: datetime):
    """다른 탭에서 변경한 필터를 오래된 화면으로 덮거나 삭제하지 못하게 한다."""
    if saved_filter.updated_at != expected_updated_at:
        raise AuthError(
            "personal_filter_stale", "필터가 변경되었습니다. 새로고침 후 다시 시도하세요.", 409
        )


def delete_personal_filter(
    session: Session,
    actor: Identity,
    project_key: str,
    filter_id: int,
    payload: PersonalFilterDelete,
) -> None:
    """현재 버전의 본인 필터만 감사 기록과 함께 삭제한다."""
    with project_service.project_operation_context(
        session, actor, "personal_filter_delete", write_operation=True
    ):
        project = project_service.require_project_member(session, actor, project_key)
        project_repository.lock_project_management(session, project.id)
        saved_filter = require_personal_filter(session, project.id, actor.id, filter_id)
        require_current_filter_revision(saved_filter, payload.expected_updated_at)
        record_personal_filter_audit(session, actor.id, saved_filter, "personal_filter.deleted")
        session.delete(saved_filter)
    logger.info("personal_filter_deleted actor_id=%s filter_id=%s", actor.id, filter_id)
