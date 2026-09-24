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
    MemberView,
    ProjectCreate,
    ProjectDetail,
    ProjectPage,
    ProjectView,
)

logger = logging.getLogger(__name__)


def record_project_audit_event(session, action, actor_id, project_id=None, **details):
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
    status = repository.get_actor_status(session, actor.id)
    if not status or not status.is_active:
        raise AuthError("authentication_required", "로그인이 필요합니다.", 401)
    if status.must_change_password:
        raise AuthError("password_change_required", "비밀번호를 먼저 변경하세요.", 403)
    return status.system_role == "SYSTEM_ADMIN"


def require_system_administrator(session, actor):
    if not is_system_administrator(session, actor):
        raise AuthError("admin_required", "시스템 관리자 권한이 필요합니다.", 403)


def build_project_view(project_row, project_role, is_system_administrator):
    return ProjectView(
        id=project_row.id,
        key=project_row.key,
        name=project_row.name,
        description=project_row.description,
        is_active=project_row.is_active,
        role=project_role,
        can_manage=is_system_administrator or project_role == "PROJECT_ADMIN",
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
    project_row, project_role = result
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
    return build_project_view(project_row, project_role, is_administrator)


def require_project_administrator(session: Session, actor: Identity, project_key: str):
    return require_project_member(session, actor, project_key, require_management_access=True)


def require_project_user_access(session: Session, actor: Identity, project_key: str):
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
            for project_row, project_role in project_rows:
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
                build_project_view(project_row, project_role, is_administrator)
                for project_row, project_role in project_rows
            ],
            total=total,
            page=page,
            page_size=size,
        )


def get_project_detail(session, actor, project_key):
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


def add_project_member(session, actor, project_key, payload: MemberCreate):
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
