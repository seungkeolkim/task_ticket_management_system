import logging
from contextlib import contextmanager

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.config import get_settings
from app.db.transaction import request_transaction
from app.domain.auth import AuthError, Identity
from app.domain.codes import ProjectRole
from app.models import AuditLog, Project, ProjectMember
from app.repositories import projects as repository
from app.repositories.auth import lock_security_write
from app.schemas.projects import (
    CandidateView,
    MemberCreate,
    MemberRoleUpdate,
    MemberView,
    ProjectCreate,
    ProjectDetail,
    ProjectFavoriteUpdate,
    ProjectPage,
    ProjectUpdate,
    ProjectView,
)

logger = logging.getLogger(__name__)

PROJECT_ROLE_RANK = {
    ProjectRole.GUEST: 0,
    ProjectRole.USER: 1,
    ProjectRole.ADMIN: 2,
}


def record_project_audit_event(session, action, actor_id, project_id=None, **details):
    """프로젝트 audit event 기록한다."""
    session.add(
        AuditLog(
            action=action,
            actor_user_id=actor_id,
            target_type="project",
            target_id=str(project_id) if project_id is not None else None,
            details=details,
        )
    )


def is_system_administrator(session: Session, actor: Identity) -> bool:
    """현재 사용자의 시스템 관리자 여부를 반환한다."""
    status = repository.get_actor_status(session, actor.id)
    if not status or not status.is_active:
        raise AuthError("authentication_required", "로그인이 필요합니다.", 401)
    if status.must_change_password:
        raise AuthError("password_change_required", "비밀번호를 먼저 변경하세요.", 403)
    return status.system_role == "SYSTEM_ADMIN"


def require_system_administrator(session, actor):
    """system 관리자 필수 조건을 검증한다."""
    if not is_system_administrator(session, actor):
        raise AuthError("admin_required", "시스템 관리자 권한이 필요합니다.", 403)


def build_project_view(
    project_row,
    project_role,
    is_system_administrator,
    is_favorite=False,
):
    """프로젝트 view 구성한다."""
    return ProjectView(
        id=project_row.id,
        key=project_row.key,
        name=project_row.name,
        description=project_row.description,
        is_active=project_row.is_active,
        role=project_role,
        can_manage=is_system_administrator or project_role == "PROJECT_ADMIN",
        is_favorite=bool(is_favorite),
    )


def require_project_member(
    session: Session,
    actor: Identity,
    project_key: str,
    *,
    require_management_access=False,
    require_write_access=False,
):
    """Use inside a top-level service transaction; override audit commits with that use case."""
    is_administrator = is_system_administrator(session, actor)
    result = repository.accessible_project(session, project_key, actor.id, is_administrator)
    if result is None:
        raise AuthError("project_not_found", "프로젝트를 찾을 수 없습니다.", 404)
    project_row, project_role, is_favorite = result
    if require_management_access and not is_administrator and project_role != "PROJECT_ADMIN":
        raise AuthError("project_admin_required", "프로젝트 관리자 권한이 필요합니다.", 403)
    if require_write_access and not is_administrator and project_role not in {
        ProjectRole.ADMIN,
        ProjectRole.USER,
    }:
        raise AuthError("project_write_required", "프로젝트 사용자 이상의 권한이 필요합니다.", 403)
    if is_administrator and (
        project_role is None
        or (require_management_access and project_role != ProjectRole.ADMIN)
        or (
            require_write_access
            and project_role not in {ProjectRole.ADMIN, ProjectRole.USER}
        )
    ):
        record_project_audit_event(
            session,
            "project.override_access",
            actor.id,
            project_row.id,
            permission=(
                "manage"
                if require_management_access
                else ("write" if require_write_access else "read")
            ),
        )
    return build_project_view(project_row, project_role, is_administrator, is_favorite)


def require_project_administrator(session: Session, actor: Identity, project_key: str):
    """프로젝트 관리자 필수 조건을 검증한다."""
    return require_project_member(session, actor, project_key, require_management_access=True)


def require_project_user_access(session: Session, actor: Identity, project_key: str):
    """프로젝트 사용자 access 필수 조건을 검증한다."""
    return require_project_member(session, actor, project_key, require_write_access=True)


@contextmanager
def project_operation_context(
    session,
    actor,
    operation_name,
    *,
    write_operation=False,
    conflict_code="project_conflict",
    conflict_message="중복되거나 변경된 정보입니다. 다시 확인하세요.",
    stale_code=None,
    stale_message="다른 사용자가 먼저 변경했습니다. 최신 내용을 다시 불러오세요.",
):
    """프로젝트 작업의 transaction과 시스템 로그를 관리한다."""
    logger.debug("%s_started actor_id=%s", operation_name, actor.id)
    try:
        with request_transaction(session):
            if write_operation:
                lock_security_write(session)
            yield
    except AuthError:
        raise
    except StaleDataError:
        logger.info("%s_rejected actor_id=%s code=stale", operation_name, actor.id)
        raise AuthError(stale_code or conflict_code, stale_message, 409) from None
    except IntegrityError:
        logger.info("%s_rejected actor_id=%s code=conflict", operation_name, actor.id)
        raise AuthError(conflict_code, conflict_message, 409) from None
    except Exception:
        logger.exception("%s_failed actor_id=%s", operation_name, actor.id)
        raise


def list_projects(
    session, actor, *, include_all_projects=False, search_query="", page=1, page_size=None
):
    """프로젝트 목록을 조회한다."""
    size = page_size if page_size is not None else get_settings().pagination.default_size
    if (
        len(search_query) > 100
        or not 1 <= page <= 1_000_000
        or size not in {10, 20, 50}
    ):
        raise AuthError("invalid_filter", "검색 조건과 페이지 범위를 확인하세요.")
    with project_operation_context(session, actor, "project_list"):
        is_administrator = is_system_administrator(session, actor)
        if include_all_projects:
            require_system_administrator(session, actor)
        project_rows, total = repository.list_projects(
            session, actor.id, include_all_projects, search_query.strip(), page, size
        )
        if include_all_projects:
            for project_row, project_role, _ in project_rows:
                if project_role is None:
                    record_project_audit_event(
                        session,
                        "project.override_access",
                        actor.id,
                        project_row.id,
                        permission="list",
                    )
        return ProjectPage(
            projects=[
                build_project_view(
                    project_row,
                    project_role,
                    is_administrator,
                    is_favorite,
                )
                for project_row, project_role, is_favorite in project_rows
            ],
            total=total,
            page=page,
            page_size=size,
        )


def set_project_favorite(
    session: Session,
    actor: Identity,
    project_key: str,
    payload: ProjectFavoriteUpdate,
) -> bool:
    """현재 사용자의 프로젝트 즐겨찾기 상태를 멱등적으로 변경한다."""
    with project_operation_context(
        session,
        actor,
        "project_favorite_update",
        write_operation=True,
    ):
        membership = repository.lock_project_membership(session, project_key, actor.id)
        if membership is None:
            raise AuthError("project_not_found", "프로젝트를 찾을 수 없습니다.", 404)
        if membership.is_favorite == payload.is_favorite:
            return membership.is_favorite
        membership.is_favorite = payload.is_favorite
        session.flush()
        return membership.is_favorite


def get_project_detail(session, actor, project_key):
    """프로젝트 상세 정보를 조회한다."""
    with project_operation_context(session, actor, "project_read"):
        project = require_project_member(session, actor, project_key)
        return ProjectDetail(
            project=project,
            members=[
                MemberView(**member_row)
                for member_row in repository.list_project_members(
                    session,
                    project.id,
                    actor.id,
                    override=project.role is None and project.can_manage,
                )
            ],
        )


def list_project_candidates(session, actor, *, project_key=None, search_query=""):
    """프로젝트 후보 목록을 조회한다."""
    if len(search_query) > 100:
        raise AuthError("invalid_filter", "검색어는 100자 이하로 입력하세요.")
    with project_operation_context(session, actor, "project_candidates"):
        if project_key is None:
            require_system_administrator(session, actor)
            project_id = None
        else:
            project_id = require_project_administrator(session, actor, project_key).id
        return [
            CandidateView(**candidate_row)
            for candidate_row in repository.list_candidate_users(
                session, search_query.strip(), project_id
            )
        ]


def create_project(session, actor, payload: ProjectCreate):
    """프로젝트 생성을 처리한다."""
    with project_operation_context(session, actor, "project_create", write_operation=True):
        require_system_administrator(session, actor)
        if not repository.active_user(session, payload.administrator_id):
            raise AuthError("invalid_user", "활성 사용자를 프로젝트 관리자로 선택하세요.")
        if repository.duplicate_key(session, payload.key):
            raise AuthError("project_conflict", "이미 사용 중인 프로젝트 키입니다.", 409)
        row = Project(
            key=payload.key,
            name=payload.name,
            description=payload.description,
            created_by_id=actor.id,
        )
        session.add(row)
        session.flush()
        session.add(
            ProjectMember(project_id=row.id, user_id=payload.administrator_id, role="PROJECT_ADMIN")
        )
        record_project_audit_event(session, "project.created", actor.id, row.id, key=row.key)
        record_project_audit_event(
            session,
            "project.member_added",
            actor.id,
            row.id,
            user_id=payload.administrator_id,
            role="PROJECT_ADMIN",
        )
        result = row.id
    logger.info("project_created actor_id=%s project_id=%s", actor.id, result)
    return result


def update_project(
    session: Session,
    actor: Identity,
    project_key: str,
    payload: ProjectUpdate,
) -> ProjectView:
    """프로젝트 이름·설명·활성 상태를 변경한다."""
    changed_fields: list[str] = []
    with project_operation_context(
        session,
        actor,
        "project_update",
        write_operation=True,
        conflict_code="project_conflict",
        conflict_message="프로젝트 정보가 변경되었습니다. 최신 내용을 다시 확인하세요.",
    ):
        project_access = require_project_administrator(session, actor, project_key)
        project_row = repository.lock_project_management(session, project_access.id)
        editable_fields = ("name", "description", "is_active")
        desired_values = {
            field_name: getattr(payload, field_name)
            for field_name in editable_fields
            if field_name in payload.model_fields_set
        }
        changed_fields = [
            field_name
            for field_name, desired_value in desired_values.items()
            if getattr(project_row, field_name) != desired_value
        ]
        if not changed_fields:
            return build_project_view(
                project_row,
                project_access.role,
                project_access.can_manage,
                project_access.is_favorite,
            )

        was_active = project_row.is_active
        for field_name in changed_fields:
            setattr(project_row, field_name, desired_values[field_name])
        session.flush()

        profile_fields = [
            field_name for field_name in changed_fields if field_name in {"name", "description"}
        ]
        if profile_fields:
            record_project_audit_event(
                session,
                "project.updated",
                actor.id,
                project_row.id,
                changed_fields=profile_fields,
            )
        if "is_active" in changed_fields:
            record_project_audit_event(
                session,
                "project.reactivated" if project_row.is_active else "project.deactivated",
                actor.id,
                project_row.id,
                before_is_active=was_active,
                after_is_active=project_row.is_active,
            )
        result = build_project_view(
            project_row,
            project_access.role,
            project_access.can_manage,
            project_access.is_favorite,
        )
    logger.info(
        "project_updated actor_id=%s project_id=%s fields=%s",
        actor.id,
        result.id,
        ",".join(changed_fields),
    )
    return result


def add_project_member(session, actor, project_key, payload: MemberCreate):
    """프로젝트 구성원 추가를 처리한다."""
    with project_operation_context(session, actor, "project_member_add", write_operation=True):
        project = require_project_administrator(session, actor, project_key)
        if not project.is_active:
            raise AuthError(
                "project_inactive", "비활성 프로젝트에는 구성원을 추가할 수 없습니다.", 409
            )
        if not repository.active_user(session, payload.user_id):
            raise AuthError("invalid_user", "활성 사용자를 선택하세요.")
        if repository.duplicate_member(session, project.id, payload.user_id):
            raise AuthError("member_conflict", "이미 참여 중인 사용자입니다.", 409)
        row = ProjectMember(project_id=project.id, user_id=payload.user_id, role=payload.role)
        session.add(row)
        session.flush()
        record_project_audit_event(
            session,
            "project.member_added",
            actor.id,
            project.id,
            user_id=payload.user_id,
            role=payload.role,
        )
        result = row.id
    logger.info(
        "project_member_added actor_id=%s project_id=%s user_id=%s",
        actor.id,
        project.id,
        payload.user_id,
    )
    return result


def _require_role_change_allowed(project, member, user_is_active, requested_role) -> None:
    """프로젝트와 사용자 활성 상태에 따른 역할 변경 범위를 검증한다."""
    current_rank = PROJECT_ROLE_RANK[ProjectRole(member.role)]
    requested_rank = PROJECT_ROLE_RANK[ProjectRole(requested_role)]
    if requested_rank <= current_rank:
        return
    if not project.is_active:
        raise AuthError(
            "project_inactive_role_expansion",
            "비활성 프로젝트에서는 참여자 권한을 확대할 수 없습니다.",
            409,
        )
    if not user_is_active:
        raise AuthError(
            "inactive_member_role_expansion",
            "비활성 사용자의 프로젝트 권한을 확대할 수 없습니다.",
            409,
        )


def _require_member_removal_constraints(session, project_id, member) -> None:
    """마지막 관리자와 활성 담당 티켓 보호 규칙을 검증한다."""
    if (
        member.role == ProjectRole.ADMIN
        and repository.project_administrator_count(session, project_id) <= 1
    ):
        raise AuthError(
            "last_project_administrator",
            "마지막 프로젝트 관리자는 역할을 낮추거나 제거할 수 없습니다.",
            409,
        )
    if repository.has_active_ticket_assignments(session, project_id, member.user_id):
        raise AuthError(
            "member_has_active_assignments",
            "미완료 담당 티켓을 먼저 재배정하거나 담당자 미지정으로 변경하세요.",
            409,
        )


def update_project_member_role(
    session: Session,
    actor: Identity,
    project_key: str,
    member_id: int,
    payload: MemberRoleUpdate,
) -> MemberView:
    """기존 프로젝트 참여자의 역할을 변경한다."""
    with project_operation_context(
        session,
        actor,
        "project_member_role_update",
        write_operation=True,
        conflict_code="project_member_conflict",
        conflict_message="참여자 정보가 변경되었습니다. 최신 목록을 다시 확인하세요.",
    ):
        project = require_project_administrator(session, actor, project_key)
        repository.lock_project_management(session, project.id)
        result = repository.project_member(session, project.id, member_id)
        if result is None:
            raise AuthError("member_not_found", "프로젝트 참여자를 찾을 수 없습니다.", 404)
        member, user_is_active = result
        if member.role == payload.role:
            current_view = repository.project_member_view(session, project.id, member.id)
            return MemberView(**current_view)

        _require_role_change_allowed(project, member, user_is_active, payload.role)
        if member.role == ProjectRole.ADMIN and payload.role != ProjectRole.ADMIN:
            if repository.project_administrator_count(session, project.id) <= 1:
                raise AuthError(
                    "last_project_administrator",
                    "마지막 프로젝트 관리자는 역할을 낮추거나 제거할 수 없습니다.",
                    409,
                )
        if payload.role == ProjectRole.GUEST and repository.has_active_ticket_assignments(
            session, project.id, member.user_id
        ):
            raise AuthError(
                "member_has_active_assignments",
                "미완료 담당 티켓을 먼저 재배정하거나 담당자 미지정으로 변경하세요.",
                409,
            )

        before_role = member.role
        member.role = payload.role
        session.flush()
        record_project_audit_event(
            session,
            "project.member_role_changed",
            actor.id,
            project.id,
            user_id=member.user_id,
            before_role=before_role,
            after_role=payload.role,
        )
        updated_view = repository.project_member_view(session, project.id, member.id)
        result_view = MemberView(**updated_view)
    logger.info(
        "project_member_role_changed actor_id=%s project_id=%s user_id=%s",
        actor.id,
        project.id,
        result_view.user_id,
    )
    return result_view


def remove_project_member(
    session: Session, actor: Identity, project_key: str, member_id: int
) -> int:
    """기존 프로젝트 참여자를 프로젝트에서 제거한다."""
    with project_operation_context(
        session,
        actor,
        "project_member_remove",
        write_operation=True,
        conflict_code="project_member_conflict",
        conflict_message="참여자 정보가 변경되었습니다. 최신 목록을 다시 확인하세요.",
    ):
        project = require_project_administrator(session, actor, project_key)
        repository.lock_project_management(session, project.id)
        result = repository.project_member(session, project.id, member_id)
        if result is None:
            raise AuthError("member_not_found", "프로젝트 참여자를 찾을 수 없습니다.", 404)
        member, _ = result
        _require_member_removal_constraints(session, project.id, member)
        removed_user_id = member.user_id
        removed_role = member.role
        session.delete(member)
        session.flush()
        record_project_audit_event(
            session,
            "project.member_removed",
            actor.id,
            project.id,
            user_id=removed_user_id,
            role=removed_role,
        )
    logger.info(
        "project_member_removed actor_id=%s project_id=%s user_id=%s",
        actor.id,
        project.id,
        removed_user_id,
    )
    return removed_user_id
