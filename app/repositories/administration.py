from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Organization, User


def organizations(session: Session) -> list[Organization]:
    return list(
        session.scalars(
            select(Organization)
            .order_by(Organization.name, Organization.id)
            .execution_options(populate_existing=True)
        )
    )


def member_counts(session: Session) -> dict[int, int]:
    return dict(
        session.execute(
            select(User.organization_id, func.count()).group_by(User.organization_id)
        ).all()
    )


def users(session: Session, query: str, page: int, page_size: int):
    filters = []
    if query:
        filters.append(
            or_(
                User.login_id.icontains(query, autoescape=True),
                User.display_name.icontains(query, autoescape=True),
                User.email.icontains(query, autoescape=True),
            )
        )
    total = session.scalar(select(func.count()).select_from(User).where(*filters)) or 0
    rows = session.execute(
        select(User, Organization.name)
        .join(Organization, User.organization_id == Organization.id)
        .where(*filters)
        .order_by(User.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return rows, total


def administrator_status(session: Session, user_id: int):
    return session.execute(
        select(User.is_active, User.must_change_password, User.system_role).where(
            User.id == user_id
        )
    ).one_or_none()


def duplicate_user(session: Session, login_id: str, email: str | None) -> bool:
    filters = [User.login_id == login_id]
    if email:
        filters.append(User.email == email)
    return session.scalar(select(User.id).where(or_(*filters)).limit(1)) is not None


def duplicate_organization(session: Session, parent_id: int | None, name: str) -> bool:
    return (
        session.scalar(
            select(Organization.id)
            .where(Organization.parent_id == parent_id, Organization.name == name)
            .limit(1)
        )
        is not None
    )
