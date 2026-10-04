import logging
from collections import defaultdict
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.transaction import request_transaction
from app.db.types import utc_now
from app.domain.auth import AuthError, Identity, hash_password, normalize_login_id
from app.models import Organization, User
from app.repositories import administration as repository
from app.repositories.auth import lock_security_write, revoke_user_sessions
from app.schemas.administration import (
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationView,
    UserCreate,
    UserPage,
    UserPasswordReset,
    UserUpdate,
    UserView,
)
from app.services.auth import record_audit_event

logger = logging.getLogger(__name__)


def require_administrator(session: Session, actor: Identity) -> None:
    """관리자 필수 조건을 검증한다."""
    status = repository.administrator_status(session, actor.id)
    if (
        not status
        or not status.is_active
        or status.must_change_password
        or status.system_role != "SYSTEM_ADMIN"
    ):
        raise AuthError("admin_required", "시스템 관리자 권한이 필요합니다.", 403)


def list_organizations(session: Session, actor: Identity) -> list[OrganizationView]:
    """조직 목록을 조회한다."""
    require_administrator(session, actor)
    organization_rows = repository.list_organizations(session)
    counts = repository.member_counts(session)
    children = defaultdict(list)
    for organization_row in organization_rows:
        children[organization_row.parent_id].append(organization_row)
    stack = [(organization_row, 0, True) for organization_row in reversed(children[None])]
    result = []
    seen = set()
    while stack:
        organization_row, depth, parent_active = stack.pop()
        if organization_row.id in seen:
            raise AuthError("invalid_organization_tree", "조직 구조를 확인하세요.", 409)
        seen.add(organization_row.id)
        selectable = parent_active and organization_row.is_active
        result.append(
            OrganizationView(
                id=organization_row.id,
                key=organization_row.key,
                name=organization_row.name,
                parent_id=organization_row.parent_id,
                description=organization_row.description,
                is_active=organization_row.is_active,
                selectable=selectable,
                depth=depth,
                member_count=counts.get(organization_row.id, 0),
            )
        )
        for child_organization in reversed(children[organization_row.id]):
            stack.append((child_organization, depth + 1, selectable))
    if len(seen) != len(organization_rows):
        raise AuthError("invalid_organization_tree", "조직 구조를 확인하세요.", 409)
    return result


def user_view(user: User, organization_name: str) -> UserView:
    """사용자 모델을 공개용 view로 변환한다."""
    return UserView(
        id=user.id,
        login_id=user.login_id,
        display_name=user.display_name,
        email=user.email,
        organization_id=user.organization_id,
        organization_name=organization_name,
        system_role=user.system_role,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        created_at=user.created_at,
        updated_at=user.updated_at,
        deactivated_at=user.deactivated_at,
    )


def list_users(
    session: Session, actor: Identity, query: str = "", page: int = 1, page_size: int | None = None
) -> UserPage:
    """사용자 목록을 조회한다."""
    require_administrator(session, actor)
    if page_size is None:
        page_size = get_settings().pagination.default_size
    if not 1 <= page <= 1_000_000 or page_size not in {10, 20, 50} or len(query) > 100:
        raise AuthError("invalid_filter", "검색 조건과 페이지 범위를 확인하세요.")
    rows, total = repository.list_users(session, query.strip(), page, page_size)
    return UserPage(
        users=[user_view(user, name) for user, name in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_active_organization(
    session: Session, actor: Identity, organization_id: int
) -> OrganizationView:
    """active 조직 정보를 조회한다."""
    row = next(
        (row for row in list_organizations(session, actor) if row.id == organization_id), None
    )
    if row is None or not row.selectable:
        raise AuthError(
            "invalid_organization", "활성 조직을 선택하세요. 상위 조직도 활성 상태여야 합니다."
        )
    return row


def create_organization(
    session: Session, actor: Identity, payload: OrganizationCreate, ip_address: str
) -> int:
    """조직 생성을 처리한다."""
    logger.debug("organization_create_started actor_id=%s", actor.id)
    try:
        with request_transaction(session):
            lock_security_write(session)
            require_administrator(session, actor)
            if payload.parent_id:
                get_active_organization(session, actor, payload.parent_id)
            if repository.duplicate_organization(session, payload.parent_id, payload.name):
                raise AuthError(
                    "organization_conflict", "같은 상위 조직에 동일한 이름이 이미 있습니다.", 409
                )
            row = Organization(
                key=str(uuid4()),
                name=payload.name,
                parent_id=payload.parent_id,
                description=payload.description,
            )
            session.add(row)
            session.flush()
            record_audit_event(
                session,
                "organization.created",
                actor.id,
                target_type="organization",
                target_id=str(row.id),
                ip_address=ip_address,
            )
            row_id = row.id
    except AuthError as error:
        logger.info("organization_create_rejected actor_id=%s code=%s", actor.id, error.code)
        raise
    except IntegrityError:
        logger.info("organization_create_rejected actor_id=%s code=conflict", actor.id)
        raise AuthError(
            "organization_conflict", "조직 정보가 중복되거나 변경되었습니다. 다시 확인하세요.", 409
        ) from None
    except Exception:
        logger.exception("organization_create_failed actor_id=%s", actor.id)
        raise
    logger.info("organization_created actor_id=%s organization_id=%s", actor.id, row_id)
    return row_id


def update_organization(
    session: Session,
    actor: Identity,
    organization_id: int,
    payload: OrganizationUpdate,
    ip_address: str,
) -> OrganizationView:
    """조직의 기본 정보·계층·활성 상태를 한 transaction에서 변경한다."""
    logger.debug(
        "organization_update_started actor_id=%s organization_id=%s", actor.id, organization_id
    )
    try:
        with request_transaction(session):
            lock_security_write(session)
            require_administrator(session, actor)
            organizations = repository.list_organizations(session)
            organization_by_id = {organization.id: organization for organization in organizations}
            organization = organization_by_id.get(organization_id)
            if organization is None:
                raise AuthError("organization_not_found", "조직을 찾을 수 없습니다.", 404)

            if payload.parent_id is not None:
                parent = organization_by_id.get(payload.parent_id)
                if parent is None:
                    raise AuthError("invalid_organization", "상위 조직을 찾을 수 없습니다.", 422)
                ancestor = parent
                visited_ancestor_ids = set()
                while ancestor is not None:
                    if ancestor.id == organization_id:
                        raise AuthError(
                            "organization_cycle",
                            "자기 자신이나 하위 조직으로 이동할 수 없습니다.",
                            409,
                        )
                    if ancestor.id in visited_ancestor_ids:
                        raise AuthError("invalid_organization_tree", "조직 구조를 확인하세요.", 409)
                    visited_ancestor_ids.add(ancestor.id)
                    ancestor = organization_by_id.get(ancestor.parent_id)
                if payload.parent_id != organization.parent_id or (
                    not organization.is_active and payload.is_active
                ):
                    get_active_organization(session, actor, payload.parent_id)

            if repository.duplicate_organization(
                session,
                payload.parent_id,
                payload.name,
                exclude_organization_id=organization_id,
            ):
                raise AuthError(
                    "organization_conflict", "같은 상위 조직에 동일한 이름이 이미 있습니다.", 409
                )

            changed_fields = [
                field_name
                for field_name, current_value, requested_value in (
                    ("name", organization.name, payload.name),
                    ("parent_id", organization.parent_id, payload.parent_id),
                    ("description", organization.description, payload.description),
                    ("is_active", organization.is_active, payload.is_active),
                )
                if current_value != requested_value
            ]
            if changed_fields:
                previously_active = organization.is_active
                organization.name = payload.name
                organization.parent_id = payload.parent_id
                organization.description = payload.description
                organization.is_active = payload.is_active
                session.flush()
                action = "organization.updated"
                if previously_active and not payload.is_active:
                    action = "organization.deactivated"
                elif not previously_active and payload.is_active:
                    action = "organization.reactivated"
                record_audit_event(
                    session,
                    action,
                    actor.id,
                    target_type="organization",
                    target_id=str(organization_id),
                    ip_address=ip_address,
                    details={"changed_fields": changed_fields},
                )
            result = next(
                organization_view
                for organization_view in list_organizations(session, actor)
                if organization_view.id == organization_id
            )
    except AuthError as error:
        logger.info(
            "organization_update_rejected actor_id=%s organization_id=%s code=%s",
            actor.id,
            organization_id,
            error.code,
        )
        raise
    except IntegrityError:
        logger.info(
            "organization_update_rejected actor_id=%s organization_id=%s code=conflict",
            actor.id,
            organization_id,
        )
        raise AuthError(
            "organization_conflict", "조직 정보가 중복되거나 변경되었습니다. 다시 확인하세요.", 409
        ) from None
    except Exception:
        logger.exception(
            "organization_update_failed actor_id=%s organization_id=%s", actor.id, organization_id
        )
        raise
    if changed_fields:
        logger.info(
            "organization_updated actor_id=%s organization_id=%s", actor.id, organization_id
        )
    return result


def create_user(session: Session, actor: Identity, payload: UserCreate, ip_address: str) -> int:
    """사용자 생성을 처리한다."""
    logger.debug("user_create_started actor_id=%s", actor.id)
    try:
        with request_transaction(session):
            lock_security_write(session)
            require_administrator(session, actor)
            login_id = normalize_login_id(payload.login_id)
            get_active_organization(session, actor, payload.organization_id)
            if repository.duplicate_user(session, login_id, payload.email):
                raise AuthError("user_conflict", "로그인 ID 또는 이메일이 이미 사용 중입니다.", 409)
            row = User(
                login_id=login_id,
                display_name=payload.display_name,
                email=payload.email,
                organization_id=payload.organization_id,
                system_role=payload.system_role,
                password_hash=hash_password(payload.password.get_secret_value()),
                must_change_password=True,
                is_active=True,
            )
            session.add(row)
            session.flush()
            record_audit_event(
                session,
                "user.created",
                actor.id,
                target_type="user",
                target_id=str(row.id),
                ip_address=ip_address,
            )
            row_id = row.id
    except AuthError as error:
        logger.info("user_create_rejected actor_id=%s code=%s", actor.id, error.code)
        raise
    except IntegrityError:
        logger.info("user_create_rejected actor_id=%s code=conflict", actor.id)
        raise AuthError(
            "user_conflict", "사용자 정보가 중복되거나 변경되었습니다. 다시 확인하세요.", 409
        ) from None
    except Exception:
        logger.exception("user_create_failed actor_id=%s", actor.id)
        raise
    logger.info("user_created actor_id=%s user_id=%s", actor.id, row_id)
    return row_id


def _managed_user(session: Session, user_id: int) -> tuple[User, str]:
    """관리 대상 사용자와 조직명을 조회하고 없으면 안전한 오류를 반환한다."""
    row = repository.get_user_with_organization(session, user_id)
    if row is None:
        raise AuthError("user_not_found", "사용자를 찾을 수 없습니다.", 404)
    return row


def _protect_last_active_administrator(session: Session, user: User, payload: UserUpdate) -> None:
    """마지막 활성 시스템 관리자를 없애는 변경을 차단한다."""
    removes_active_administrator = (
        user.is_active
        and user.system_role == "SYSTEM_ADMIN"
        and (not payload.is_active or payload.system_role != "SYSTEM_ADMIN")
    )
    if removes_active_administrator and repository.active_system_administrator_count(session) <= 1:
        raise AuthError(
            "last_active_administrator",
            "마지막 활성 시스템 관리자는 비활성화하거나 일반 사용자로 변경할 수 없습니다.",
            409,
        )


def update_user(
    session: Session,
    actor: Identity,
    user_id: int,
    payload: UserUpdate,
    ip_address: str,
) -> UserView:
    """사용자 기본 정보·역할·활성 상태를 수정한다."""
    logger.debug("user_update_started actor_id=%s target_user_id=%s", actor.id, user_id)
    try:
        with request_transaction(session):
            lock_security_write(session)
            require_administrator(session, actor)
            user, organization_name = _managed_user(session, user_id)
            selected_organization = get_active_organization(session, actor, payload.organization_id)
            if repository.duplicate_user(
                session,
                user.login_id,
                payload.email,
                exclude_user_id=user.id,
            ):
                raise AuthError("user_conflict", "이메일이 이미 사용 중입니다.", 409)
            _protect_last_active_administrator(session, user, payload)
            previous_active = user.is_active
            changed_fields = [
                field_name
                for field_name, current_value, requested_value in (
                    ("display_name", user.display_name, payload.display_name),
                    ("email", user.email, payload.email),
                    ("organization_id", user.organization_id, payload.organization_id),
                    ("system_role", user.system_role, payload.system_role),
                    ("is_active", user.is_active, payload.is_active),
                )
                if current_value != requested_value
            ]
            changed = bool(changed_fields)
            if changed:
                user.display_name = payload.display_name
                user.email = payload.email
                user.organization_id = payload.organization_id
                user.system_role = payload.system_role
                user.is_active = payload.is_active
                if previous_active and not payload.is_active:
                    user.deactivated_at = utc_now()
                    user.deactivated_by_id = actor.id
                    revoke_user_sessions(session, user.id)
                    audit_action = "user.deactivated"
                elif not previous_active and payload.is_active:
                    user.deactivated_at = None
                    user.deactivated_by_id = None
                    audit_action = "user.reactivated"
                else:
                    audit_action = "user.updated"
                session.flush()
                record_audit_event(
                    session,
                    audit_action,
                    actor.id,
                    target_type="user",
                    target_id=str(user.id),
                    ip_address=ip_address,
                    details={"changed_fields": changed_fields},
                )
                organization_name = selected_organization.name
            result = user_view(user, organization_name)
    except AuthError as error:
        logger.info(
            "user_update_rejected actor_id=%s target_user_id=%s code=%s",
            actor.id,
            user_id,
            error.code,
        )
        raise
    except IntegrityError:
        logger.info(
            "user_update_rejected actor_id=%s target_user_id=%s code=conflict",
            actor.id,
            user_id,
        )
        raise AuthError(
            "user_conflict", "사용자 정보가 중복되거나 변경되었습니다. 다시 확인하세요.", 409
        ) from None
    except Exception:
        logger.exception("user_update_failed actor_id=%s target_user_id=%s", actor.id, user_id)
        raise
    if changed:
        logger.info("user_updated actor_id=%s target_user_id=%s", actor.id, user_id)
    return result


def reset_user_password(
    session: Session,
    actor: Identity,
    user_id: int,
    payload: UserPasswordReset,
    ip_address: str,
) -> UserView:
    """관리자가 임시 비밀번호를 설정하고 대상 사용자의 session을 폐기한다."""
    logger.debug("user_password_reset_started actor_id=%s target_user_id=%s", actor.id, user_id)
    try:
        with request_transaction(session):
            lock_security_write(session)
            require_administrator(session, actor)
            user, organization_name = _managed_user(session, user_id)
            user.password_hash = hash_password(payload.temporary_password.get_secret_value())
            user.must_change_password = True
            revoke_user_sessions(session, user.id)
            session.flush()
            record_audit_event(
                session,
                "user.password_reset",
                actor.id,
                target_type="user",
                target_id=str(user.id),
                ip_address=ip_address,
            )
            result = user_view(user, organization_name)
    except AuthError as error:
        logger.info(
            "user_password_reset_rejected actor_id=%s target_user_id=%s code=%s",
            actor.id,
            user_id,
            error.code,
        )
        raise
    except Exception:
        logger.exception(
            "user_password_reset_failed actor_id=%s target_user_id=%s", actor.id, user_id
        )
        raise
    logger.info("user_password_reset actor_id=%s target_user_id=%s", actor.id, user_id)
    return result
