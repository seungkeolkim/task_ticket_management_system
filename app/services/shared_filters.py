import logging
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.domain.auth import AuthError, Identity
from app.models import AuditLog, SavedFilter
from app.repositories import projects as project_repository
from app.repositories import shared_filters as repository
from app.schemas.contracts import TicketFilter
from app.schemas.shared_filters import (
    SharedFilterCreate,
    SharedFilterDelete,
    SharedFilterSummary,
    SharedFilterUpdate,
    SharedFilterView,
)
from app.services import projects as project_service
from app.services.saved_filter_definitions import validate_saved_filter_definition

logger = logging.getLogger(__name__)


def shared_filter_summary(saved_filter: SavedFilter) -> SharedFilterSummary:
    """ORM row를 공유 필터 요약으로 변환한다."""
    return SharedFilterSummary(
        id=saved_filter.id, name=saved_filter.name, updated_at=saved_filter.updated_at
    )


def require_shared_filter(session, project_id, filter_id) -> SavedFilter:
    """프로젝트 공유 필터만 반환하며 개인·다른 프로젝트 필터를 숨긴다."""
    saved_filter = repository.get_shared_filter(session, project_id, filter_id)
    if saved_filter is None:
        raise AuthError("shared_filter_not_found", "공유 필터를 찾을 수 없습니다.", 404)
    return saved_filter


def validate_unique_name(session, project_id, name, excluded_id=None) -> None:
    """쓰기 잠금 안에서 같은 프로젝트 공유 범위의 이름 중복을 차단한다."""
    if repository.shared_filter_name_exists(session, project_id, name, excluded_id):
        raise AuthError("shared_filter_name_conflict", "같은 이름의 공유 필터가 있습니다.", 409)


def record_shared_filter_audit(session, actor_id, saved_filter, action) -> None:
    """공유 검색 내용 없이 필터 식별자와 변경 종류만 감사 기록한다."""
    session.add(
        AuditLog(
            action=action,
            actor_user_id=actor_id,
            target_type="saved_filter",
            target_id=str(saved_filter.id),
            details={"project_id": saved_filter.project_id},
        )
    )


def list_shared_filters(session: Session, actor: Identity, project_key: str):
    """현재 프로젝트 접근 권한과 공유 범위를 적용해 목록을 반환한다."""
    with project_service.project_operation_context(session, actor, "shared_filter_list"):
        project = project_service.require_project_member(session, actor, project_key)
        return [
            shared_filter_summary(saved_filter)
            for saved_filter in repository.list_shared_filters(session, project.id)
        ]


def get_shared_filter(session: Session, actor: Identity, project_key: str, filter_id: int):
    """불러올 때마다 프로젝트 권한·저장 schema·참조를 다시 검사한다."""
    with project_service.project_operation_context(session, actor, "shared_filter_read"):
        project = project_service.require_project_member(session, actor, project_key)
        saved_filter = require_shared_filter(session, project.id, filter_id)
        try:
            if saved_filter.schema_version != 1:
                raise ValueError("unsupported schema")
            definition = TicketFilter.model_validate(saved_filter.definition)
            validate_saved_filter_definition(session, project.id, definition)
        except (ValidationError, ValueError, AuthError):
            raise AuthError(
                "saved_filter_invalid",
                "저장된 조건을 사용할 수 없습니다. "
                "프로젝트 관리자에게 조건 수정 또는 삭제를 요청하세요.",
                409,
            ) from None
        return SharedFilterView(
            **shared_filter_summary(saved_filter).model_dump(), definition=definition
        )


def create_shared_filter(
    session: Session, actor: Identity, project_key: str, payload: SharedFilterCreate
):
    """프로젝트 공유 필터와 감사 기록을 한 transaction으로 생성한다."""
    with project_service.project_operation_context(
        session, actor, "shared_filter_create", write_operation=True
    ):
        project = require_shared_filter_management(session, actor, project_key)
        validate_unique_name(session, project.id, payload.name)
        validate_saved_filter_definition(session, project.id, payload.definition)
        saved_filter = SavedFilter(
            project_id=project.id,
            owner_id=actor.id,
            name=payload.name,
            visibility="PROJECT",
            schema_version=1,
            definition=payload.definition.model_dump(mode="json"),
        )
        session.add(saved_filter)
        session.flush()
        record_shared_filter_audit(session, actor.id, saved_filter, "shared_filter.created")
        result = shared_filter_summary(saved_filter)
    logger.info("shared_filter_created actor_id=%s filter_id=%s", actor.id, result.id)
    return result


def update_shared_filter(
    session: Session,
    actor: Identity,
    project_key: str,
    filter_id: int,
    payload: SharedFilterUpdate,
):
    """동시 수정과 이름 중복을 차단하며 이름 또는 조건을 변경한다."""
    with project_service.project_operation_context(
        session, actor, "shared_filter_update", write_operation=True
    ):
        project = require_shared_filter_management(session, actor, project_key)
        saved_filter = require_shared_filter(session, project.id, filter_id)
        require_current_filter_revision(saved_filter, payload.expected_updated_at)
        name = payload.name if payload.name is not None else saved_filter.name
        validate_unique_name(session, project.id, name, filter_id)
        definition = saved_filter.definition
        if payload.definition is not None:
            validate_saved_filter_definition(session, project.id, payload.definition)
            definition = payload.definition.model_dump(mode="json")
        if (
            name == saved_filter.name
            and definition == saved_filter.definition
            and (payload.definition is None or saved_filter.schema_version == 1)
        ):
            return shared_filter_summary(saved_filter)
        saved_filter.name = name
        saved_filter.definition = definition
        if payload.definition is not None:
            saved_filter.schema_version = 1
        saved_filter.updated_at = max(
            datetime.now(UTC), saved_filter.updated_at + timedelta(microseconds=1)
        )
        session.flush()
        record_shared_filter_audit(session, actor.id, saved_filter, "shared_filter.updated")
        result = shared_filter_summary(saved_filter)
    logger.info("shared_filter_updated actor_id=%s filter_id=%s", actor.id, filter_id)
    return result


def require_current_filter_revision(saved_filter: SavedFilter, expected_updated_at: datetime):
    """다른 탭에서 변경한 필터를 오래된 화면으로 덮거나 삭제하지 못하게 한다."""
    if saved_filter.updated_at != expected_updated_at:
        raise AuthError(
            "shared_filter_stale", "필터가 변경되었습니다. 새로고침 후 다시 시도하세요.", 409
        )


def delete_shared_filter(
    session: Session,
    actor: Identity,
    project_key: str,
    filter_id: int,
    payload: SharedFilterDelete,
) -> None:
    """현재 버전의 공유 필터만 감사 기록과 함께 삭제한다."""
    with project_service.project_operation_context(
        session, actor, "shared_filter_delete", write_operation=True
    ):
        project = require_shared_filter_management(session, actor, project_key)
        saved_filter = require_shared_filter(session, project.id, filter_id)
        require_current_filter_revision(saved_filter, payload.expected_updated_at)
        record_shared_filter_audit(session, actor.id, saved_filter, "shared_filter.deleted")
        session.delete(saved_filter)
    logger.info("shared_filter_deleted actor_id=%s filter_id=%s", actor.id, filter_id)


def require_shared_filter_management(session: Session, actor: Identity, project_key: str):
    """활성 프로젝트 관리 권한과 쓰기 잠금을 요구한다."""
    project = project_service.require_project_administrator(session, actor, project_key)
    project_repository.lock_project_management(session, project.id)
    if not project.is_active:
        raise AuthError(
            "project_inactive", "비활성 프로젝트의 공유 필터는 변경할 수 없습니다.", 409
        )
    return project
