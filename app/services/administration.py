import logging
from collections import defaultdict
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.transaction import request_transaction
from app.domain.auth import AuthError, Identity, hash_password, normalize_login_id
from app.models import Organization, User
from app.repositories import administration as repository
from app.repositories.auth import lock_security_write
from app.schemas.administration import (
    OrganizationCreate,
    OrganizationView,
    UserCreate,
    UserPage,
    UserView,
)
from app.services.auth import audit

logger = logging.getLogger(__name__)


def require_administrator(session: Session, actor: Identity) -> None:
    status = repository.administrator_status(session, actor.id)
    if (
        not status
        or not status.is_active
        or status.must_change_password
        or status.system_role != "SYSTEM_ADMIN"
    ):
        raise AuthError("admin_required", "시스템 관리자 권한이 필요합니다.", 403)


def organization_list(session: Session, actor: Identity) -> list[OrganizationView]:
    require_administrator(session, actor)
    rows = repository.organizations(session)
    counts = repository.member_counts(session)
    children = defaultdict(list)
    for row in rows:
        children[row.parent_id].append(row)
    stack = [(row, 0, True) for row in reversed(children[None])]
    result = []
    seen = set()
    while stack:
        row, depth, parent_active = stack.pop()
        if row.id in seen:
            raise AuthError("invalid_organization_tree", "조직 구조를 확인하세요.", 409)
        seen.add(row.id)
        selectable = parent_active and row.is_active
        result.append(
            OrganizationView(
                id=row.id,
                key=row.key,
                name=row.name,
                parent_id=row.parent_id,
                description=row.description,
                is_active=row.is_active,
                selectable=selectable,
                depth=depth,
                member_count=counts.get(row.id, 0),
            )
        )
        stack.extend((child, depth + 1, selectable) for child in reversed(children[row.id]))
    if len(seen) != len(rows):
        raise AuthError("invalid_organization_tree", "조직 구조를 확인하세요.", 409)
    return result


def user_view(user: User, organization_name: str) -> UserView:
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
    )


def user_list(
    session: Session, actor: Identity, query: str = "", page: int = 1, page_size: int | None = None
) -> UserPage:
    require_administrator(session, actor)
    if page_size is None:
        page_size = get_settings().pagination.default_size
    if not 1 <= page <= 1_000_000 or page_size not in {10, 20, 50} or len(query) > 100:
        raise AuthError("invalid_filter", "검색 조건과 페이지 범위를 확인하세요.")
    rows, total = repository.users(session, query.strip(), page, page_size)
    return UserPage(
        users=[user_view(user, name) for user, name in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


def active_organization(
    session: Session, actor: Identity, organization_id: int
) -> OrganizationView:
    row = next(
        (row for row in organization_list(session, actor) if row.id == organization_id), None
    )
    if row is None or not row.selectable:
        raise AuthError(
            "invalid_organization", "활성 조직을 선택하세요. 상위 조직도 활성 상태여야 합니다."
        )
    return row


def create_organization(
    session: Session, actor: Identity, payload: OrganizationCreate, ip_address: str
) -> int:
    logger.debug("organization_create_started actor_id=%s", actor.id)
    try:
        with request_transaction(session):
            lock_security_write(session)
            require_administrator(session, actor)
            if payload.parent_id:
                active_organization(session, actor, payload.parent_id)
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
            audit(
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


def create_user(session: Session, actor: Identity, payload: UserCreate, ip_address: str) -> int:
    logger.debug("user_create_started actor_id=%s", actor.id)
    try:
        with request_transaction(session):
            lock_security_write(session)
            require_administrator(session, actor)
            login_id = normalize_login_id(payload.login_id)
            active_organization(session, actor, payload.organization_id)
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
            audit(
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
