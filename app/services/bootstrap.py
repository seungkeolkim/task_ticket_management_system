import logging
import os
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.transaction import transaction_scope
from app.domain.auth import hash_password, normalize_login_id
from app.models import SystemRole, User
from app.repositories import auth as repository
from app.services.auth import record_audit_event

logger = logging.getLogger(__name__)


def bootstrap_admin(
    session_factory: Callable[[], Session],
    settings: Settings,
    login_id: str,
    password: str,
    display_name: str,
) -> int | None:
    """관리자 bootstrap을 수행한다."""
    logger.info("auth_bootstrap_started")
    with transaction_scope(session_factory) as session:
        repository.lock_security_write(session)
        if repository.count_users(session):
            logger.info("auth_bootstrap_skipped reason=users_exist")
            return None
        login_id = normalize_login_id(login_id)
        if not display_name.strip() or len(display_name) > 200:
            raise ValueError("Bootstrap display name must contain 1 to 200 characters")
        password_hash = hash_password(password)
        organization = repository.bootstrap_organization(
            session, settings.bootstrap.organization_key, settings.bootstrap.organization_name
        )
        user = User(
            login_id=login_id,
            display_name=display_name.strip(),
            password_hash=password_hash,
            organization_id=organization.id,
            system_role=SystemRole.SYSTEM_ADMIN,
            must_change_password=True,
        )
        session.add(user)
        session.flush()
        record_audit_event(
            session,
            "auth.bootstrap_admin_created",
            user.id,
            target_type="user",
            target_id=str(user.id),
        )
        user_id = user.id
    logger.info("auth_bootstrap_completed user_id=%s", user_id)
    return user_id


def bootstrap_from_environment(session_factory: Callable[[], Session], settings: Settings) -> None:
    """from 환경 변수 bootstrap을 수행한다."""
    keys = (
        "BOOTSTRAP_ADMIN_LOGIN_ID",
        "BOOTSTRAP_ADMIN_PASSWORD",
        "BOOTSTRAP_ADMIN_PASSWORD_FILE",
        "BOOTSTRAP_ADMIN_DISPLAY_NAME",
    )
    if not any(os.getenv(key) for key in keys):
        return
    with session_factory() as session:
        if repository.count_users(session):
            logger.info("auth_bootstrap_skipped reason=users_exist")
            return
    login_id = os.getenv(keys[0], "")
    password = os.getenv(keys[1], "")
    secret_file = os.getenv(keys[2], "")
    if password and secret_file:
        raise ValueError("Set either bootstrap password or password file, not both")
    if secret_file:
        with open(secret_file, encoding="utf-8") as handle:
            password = handle.read(4096).rstrip("\r\n")
    if not login_id or not password:
        raise ValueError("Bootstrap requires a login ID and password (environment or secret file)")
    bootstrap_admin(
        session_factory, settings, login_id, password, os.getenv(keys[3]) or "시스템 관리자"
    )
