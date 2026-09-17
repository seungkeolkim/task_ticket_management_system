import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.transaction import request_transaction
from app.db.types import utc_now
from app.domain.auth import (
    AuthError,
    Identity,
    hash_password,
    new_session_token,
    normalize_login_id,
    token_digest,
    validate_password,
    verify_password,
)
from app.models import AuditLog, User, UserSession
from app.repositories import auth as repository

logger = logging.getLogger(__name__)


def _identity(user: User, session_id: int) -> Identity:
    return Identity(
        user.id,
        user.login_id,
        user.display_name,
        user.organization.name,
        user.system_role,
        user.must_change_password,
        session_id,
    )


def current_identity(session: Session, token: str | None) -> Identity | None:
    if not token or len(token) != 43:
        return None
    stored = repository.find_active_session(session, token_digest(token), utc_now())
    return _identity(stored.user, stored.id) if stored else None


def audit(
    session: Session,
    action: str,
    actor_id: int | None = None,
    *,
    ip_address: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_user_id=actor_id,
            action=action,
            ip_address=ip_address,
            target_type=target_type,
            target_id=target_id,
            details={},
        )
    )


def login(
    session: Session,
    settings: Settings,
    login_id: str,
    password: str,
    ip_address: str,
    previous_token: str | None = None,
) -> tuple[str, Identity]:
    error: AuthError | None = None
    identity_key = token_digest(login_id.strip().lower()[:100])
    now = utc_now()
    logger.debug("auth_login_started")
    with request_transaction(session):
        repository.lock_security_write(session)
        since = now - timedelta(seconds=settings.auth.login_window_seconds)
        limited = (
            repository.failure_count(session, since, identity_key=identity_key)
            >= settings.auth.login_max_failures
            or repository.failure_count(session, since, ip_address=ip_address)
            >= settings.auth.login_max_ip_failures
        )
        if limited:
            # Rejected requests do not extend the failure window or grow the audit table.
            logger.warning("auth_login_rate_limited")
            error = AuthError(
                "login_rate_limited",
                "로그인 시도가 많습니다. 잠시 후 다시 시도하세요.",
                429,
                settings.auth.login_window_seconds,
            )
        else:
            try:
                normalized = normalize_login_id(login_id)
            except AuthError:
                normalized = ""
            user = repository.find_user(session, normalized) if normalized else None
            verified_hash = user.password_hash if user else None
            verified = verify_password(password, verified_hash)
            if (
                not verified
                or user is None
                or not user.is_active
                or not repository.lock_verified_user(session, user.id, verified_hash)
            ):
                audit(
                    session,
                    "auth.login_failed",
                    ip_address=ip_address,
                    target_type="login_identity",
                    target_id=identity_key,
                )
                logger.info("auth_login_rejected")
                error = AuthError(
                    "invalid_credentials", "로그인 ID 또는 비밀번호를 확인하세요.", 401
                )
            else:
                session.refresh(user)
                token = new_session_token()
                if previous_token and len(previous_token) == 43:
                    repository.revoke_token(session, token_digest(previous_token))
                stored = UserSession(
                    user_id=user.id,
                    token_hash=token_digest(token),
                    created_at=now,
                    expires_at=now + timedelta(minutes=settings.session.lifetime_minutes),
                )
                session.add(stored)
                session.flush()
                identity = _identity(user, stored.id)
                audit(session, "auth.login_succeeded", user.id, ip_address=ip_address)
    if error:
        raise error
    logger.info("auth_login_completed user_id=%s", identity.id)
    return token, identity


def logout(session: Session, identity: Identity, token: str, ip_address: str) -> None:
    with request_transaction(session):
        repository.revoke_token(session, token_digest(token))
        audit(session, "auth.logout", identity.id, ip_address=ip_address)
    logger.info("auth_logout_completed user_id=%s", identity.id)


def change_password(
    session: Session,
    settings: Settings,
    identity: Identity,
    current_password: str,
    new_password: str,
    confirmation: str,
    ip_address: str,
) -> None:
    if new_password != confirmation:
        raise AuthError("password_confirmation_mismatch", "새 비밀번호 확인이 일치하지 않습니다.")
    validate_password(new_password)
    if current_password == new_password:
        raise AuthError("password_unchanged", "현재 비밀번호와 다른 비밀번호를 입력하세요.")
    error: AuthError | None = None
    with request_transaction(session):
        repository.lock_security_write(session)
        # Share the login throttle to prevent password guessing through a stolen session.
        since = utc_now() - timedelta(seconds=settings.auth.login_window_seconds)
        identity_key = token_digest(identity.login_id)
        if (
            repository.failure_count(session, since, identity_key=identity_key)
            >= settings.auth.login_max_failures
            or repository.failure_count(session, since, ip_address=ip_address)
            >= settings.auth.login_max_ip_failures
        ):
            error = AuthError(
                "login_rate_limited",
                "시도가 많습니다. 잠시 후 다시 시도하세요.",
                429,
                settings.auth.login_window_seconds,
            )
        else:
            user = repository.find_user(session, identity.login_id)
            old_hash = user.password_hash if user else None
            if (
                not verify_password(current_password, old_hash)
                or user is None
                or not user.is_active
            ):
                audit(
                    session,
                    "auth.login_failed",
                    identity.id,
                    ip_address=ip_address,
                    target_type="login_identity",
                    target_id=identity_key,
                )
                error = AuthError("invalid_current_password", "현재 비밀번호를 확인하세요.", 400)
            elif not repository.replace_password(
                session, user.id, old_hash, hash_password(new_password)
            ):
                error = AuthError(
                    "credentials_changed", "계정 정보가 변경되었습니다. 다시 로그인하세요.", 409
                )
            else:
                repository.revoke_user_sessions(session, user.id)
                audit(session, "auth.password_changed", user.id, ip_address=ip_address)
    if error:
        logger.info("auth_password_change_rejected user_id=%s code=%s", identity.id, error.code)
        raise error
    logger.info("auth_password_change_completed user_id=%s", identity.id)
