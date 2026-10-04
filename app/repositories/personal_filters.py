from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SavedFilter


def personal_filter_query(project_id: int, owner_id: int):
    """다른 사용자·프로젝트·공유 필터를 제외하는 query를 구성한다."""
    return select(SavedFilter).where(
        SavedFilter.project_id == project_id,
        SavedFilter.owner_id == owner_id,
        SavedFilter.visibility == "PERSONAL",
    )


def list_personal_filters(session: Session, project_id: int, owner_id: int):
    """프로젝트 내 본인 필터만 이름·ID 순으로 조회한다."""
    return session.scalars(
        personal_filter_query(project_id, owner_id).order_by(SavedFilter.name, SavedFilter.id)
    ).all()


def get_personal_filter(session: Session, project_id: int, owner_id: int, filter_id: int):
    """소유 범위 안에서 최신 필터 row를 조회한다."""
    query = personal_filter_query(project_id, owner_id).where(SavedFilter.id == filter_id)
    return session.scalar(query.execution_options(populate_existing=True))


def personal_filter_name_exists(
    session: Session, project_id: int, owner_id: int, name: str, excluded_id: int | None = None
) -> bool:
    """같은 사용자·프로젝트의 정규화된 동일 이름 존재 여부를 반환한다."""
    query = personal_filter_query(project_id, owner_id).where(SavedFilter.name == name)
    if excluded_id is not None:
        query = query.where(SavedFilter.id != excluded_id)
    return session.scalar(query.limit(1)) is not None
