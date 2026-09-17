"""Queries and atomic guards used by the authentication application services."""

from datetime import datetime

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from app.models import AuditLog, Organization, User, UserSession


def user_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(User)) or 0


def find_user(session: Session, login_id: str) -> User | None:
    return session.scalar(select(User).where(User.login_id == login_id))


def find_active_session(session: Session, token_hash: str, now: datetime) -> UserSession | None:
    return session.scalar(
        select(UserSession)
        .join(User)
        .where(
            UserSession.token_hash == token_hash,
            UserSession.expires_at > now,
            UserSession.revoked_at.is_(None),
            User.is_active.is_(True),
        )
    )


def lock_verified_user(session: Session, user_id: int, verified_hash: str) -> bool:
    # Serialize session creation with concurrent password changes/deactivation.
    result = session.execute(
        update(User)
        .where(
            User.id == user_id,
            User.password_hash == verified_hash,
            User.is_active.is_(True),
        )
        .values(updated_at=User.updated_at)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def replace_password(session: Session, user_id: int, verified_hash: str, new_hash: str) -> bool:
    result = session.execute(
        update(User)
        .where(
            User.id == user_id,
            User.password_hash == verified_hash,
            User.is_active.is_(True),
        )
        .values(password_hash=new_hash, must_change_password=False)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def revoke_token(session: Session, token_hash: str) -> None:
    session.execute(delete(UserSession).where(UserSession.token_hash == token_hash))


def revoke_user_sessions(session: Session, user_id: int) -> None:
    session.execute(delete(UserSession).where(UserSession.user_id == user_id))


def failure_count(
    session: Session,
    since: datetime,
    *,
    identity_key: str | None = None,
    ip_address: str | None = None,
) -> int:
    query = (
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.action == "auth.login_failed",
            AuditLog.occurred_at >= since,
        )
    )
    if identity_key is not None:
        query = query.where(
            AuditLog.target_type == "login_identity", AuditLog.target_id == identity_key
        )
    if ip_address is not None:
        query = query.where(AuditLog.ip_address == ip_address)
    return session.scalar(query) or 0


def lock_security_write(session: Session) -> None:
    # The supported deployment is SQLite. Keep engine-specific locking in this adapter.
    if session.get_bind().dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
    else:
        raise RuntimeError("Authentication write locking must be verified for this database engine")


def bootstrap_organization(session: Session, key: str, name: str) -> Organization:
    organization = session.scalar(select(Organization).where(Organization.key == key))
    if organization is None:
        organization = Organization(key=key, name=name)
        session.add(organization)
        session.flush()
    if not organization.is_active:
        raise ValueError("Bootstrap organization must be active")
    return organization
