from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.types import utc_now
from app.models import AuditLog, Organization, SystemRole, User, UserSession


def test_identity_models_round_trip(db_session: Session) -> None:
    """모델 관련 동작을 검증한다."""
    organization = Organization(key="engineering", name="Engineering")
    user = User(
        login_id="admin",
        display_name="Administrator",
        email="admin@example.com",
        password_hash="not-a-real-password-hash",
        system_role=SystemRole.SYSTEM_ADMIN,
        organization=organization,
    )
    session = UserSession(
        user=user,
        token_hash="a" * 64,
        expires_at=utc_now() + timedelta(hours=8),
    )
    audit_log = AuditLog(
        actor=user,
        action="user.created",
        target_type="user",
        target_id="pending",
        details={"login_id": "admin"},
    )
    db_session.add_all([organization, user, session, audit_log])
    db_session.commit()

    stored_user = db_session.scalar(select(User).where(User.login_id == "admin"))
    assert stored_user is not None
    assert stored_user.organization.key == "engineering"
    assert stored_user.sessions[0].token_hash == "a" * 64
    assert stored_user.audit_events[0].details == {"login_id": "admin"}
