from collections.abc import Generator

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.engine import create_database_engine

settings = get_settings()
engine = create_database_engine(
    settings.database_url,
    echo=settings.database.echo,
    pool_pre_ping=settings.database.pool_pre_ping,
)


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
