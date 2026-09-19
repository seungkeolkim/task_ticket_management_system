import logging
from contextlib import contextmanager

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.transaction import request_transaction
from app.domain.auth import AuthError, Identity
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


def audit(session, action, actor_id, project_id=None, **details):
    session.add(
        AuditLog(
            action=action,
            actor_user_id=actor_id,
            target_type="project",
            target_id=str(project_id) if project_id is not None else None,
            details=details,
        )
    )


def actor_is_admin(session: Session, actor: Identity) -> bool:
    status = repository.actor_status(session, actor.id)
    if not status or not status.is_active:
        raise AuthError("authentication_required", "로그인이 필요합니다.", 401)
    if status.must_change_password:
        raise AuthError("password_change_required", "비밀번호를 먼저 변경하세요.", 403)
    return status.system_role == "SYSTEM_ADMIN"


def require_system_admin(session, actor):
    if not actor_is_admin(session, actor):
        raise AuthError("admin_required", "시스템 관리자 권한이 필요합니다.", 403)


def view(row, role, admin):
    return ProjectView(
        id=row.id,
        key=row.key,
        name=row.name,
        description=row.description,
        is_active=row.is_active,
        role=role,
        can_manage=admin or role == "PROJECT_ADMIN",
    )


def require_project_member(session: Session, actor: Identity, key: str, *, manage=False):
    """Use inside a top-level service transaction; override audit commits with that use case."""
    admin = actor_is_admin(session, actor)
    result = repository.accessible_project(session, key, actor.id, admin)
    if result is None:
        raise AuthError("project_not_found", "프로젝트를 찾을 수 없습니다.", 404)
    row, role = result
    if manage and not admin and role != "PROJECT_ADMIN":
        raise AuthError("project_admin_required", "프로젝트 관리자 권한이 필요합니다.", 403)
    if admin and (role is None or (manage and role != "PROJECT_ADMIN")):
        audit(
            session,
            "project.override_access",
            actor.id,
            row.id,
            permission="manage" if manage else "read",
        )
    return view(row, role, admin)


def require_project_admin(session: Session, actor: Identity, key: str):
    return require_project_member(session, actor, key, manage=True)


@contextmanager
def operation(session, actor, event, *, write=False):
    logger.debug("%s_started actor_id=%s", event, actor.id)
    try:
        with request_transaction(session):
            if write:
                lock_security_write(session)
            yield
    except AuthError:
        raise
    except IntegrityError:
        logger.info("%s_rejected actor_id=%s code=conflict", event, actor.id)
        raise AuthError(
            "project_conflict", "중복되거나 변경된 정보입니다. 다시 확인하세요.", 409
        ) from None
    except Exception:
        logger.exception("%s_failed actor_id=%s", event, actor.id)
        raise


def project_list(session, actor, *, all_projects=False, q="", page=1, page_size=None):
    size = page_size if page_size is not None else get_settings().pagination.default_size
    if len(q) > 100 or not 1 <= page <= 1_000_000 or size not in {10, 20, 50}:
        raise AuthError("invalid_filter", "검색 조건과 페이지 범위를 확인하세요.")
    with operation(session, actor, "project_list"):
        admin = actor_is_admin(session, actor)
        if all_projects:
            require_system_admin(session, actor)
        rows, total = repository.projects(session, actor.id, all_projects, q.strip(), page, size)
        if all_projects:
            for row, role in rows:
                if role is None:
                    audit(session, "project.override_access", actor.id, row.id, permission="list")
        return ProjectPage(
            projects=[view(row, role, admin) for row, role in rows],
            total=total,
            page=page,
            page_size=size,
        )


def project_detail(session, actor, key):
    with operation(session, actor, "project_read"):
        project = require_project_member(session, actor, key)
        return ProjectDetail(
            project=project,
            members=[
                MemberView(**row)
                for row in repository.members(
                    session,
                    project.id,
                    actor.id,
                    override=project.role is None and project.can_manage,
                )
            ],
        )


def candidate_list(session, actor, *, key=None, q=""):
    if len(q) > 100:
        raise AuthError("invalid_filter", "검색어는 100자 이하로 입력하세요.")
    with operation(session, actor, "project_candidates"):
        if key is None:
            require_system_admin(session, actor)
            project_id = None
        else:
            project_id = require_project_admin(session, actor, key).id
        return [
            CandidateView(**row) for row in repository.candidates(session, q.strip(), project_id)
        ]


def create_project(session, actor, payload: ProjectCreate):
    with operation(session, actor, "project_create", write=True):
        require_system_admin(session, actor)
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
        audit(session, "project.created", actor.id, row.id, key=row.key)
        audit(
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


def add_member(session, actor, key, payload: MemberCreate):
    with operation(session, actor, "project_member_add", write=True):
        project = require_project_admin(session, actor, key)
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
        audit(
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
