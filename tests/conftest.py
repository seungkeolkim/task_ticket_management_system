from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.engine import create_database_engine
from app.db.session import get_db_session
from app.main import app


@pytest.fixture(autouse=True)
def isolate_bootstrap_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """bootstrap 환경 변수를 테스트별로 격리한다."""
    for name in (
        "BOOTSTRAP_ADMIN_LOGIN_ID",
        "BOOTSTRAP_ADMIN_PASSWORD",
        "BOOTSTRAP_ADMIN_PASSWORD_FILE",
        "BOOTSTRAP_ADMIN_DISPLAY_NAME",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """테스트용 DB URL fixture를 제공한다."""
    database_path = (tmp_path / "test.db").as_posix()
    return f"sqlite:///{database_path}"


@pytest.fixture
def alembic_config(database_url: str) -> Config:
    """테스트용 Alembic 설정 fixture를 제공한다."""
    config = Config("alembic.ini")
    config.attributes["database_url"] = database_url
    return config


@pytest.fixture
def migrated_database_url(alembic_config: Config, database_url: str) -> Iterator[str]:
    """migration이 적용된 테스트 DB URL을 제공한다."""
    command.upgrade(alembic_config, "head")
    yield database_url
    command.downgrade(alembic_config, "base")


@pytest.fixture
def db_engine(migrated_database_url: str) -> Iterator[Engine]:
    """테스트용 DB engine fixture를 제공한다."""
    engine = create_database_engine(migrated_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session_factory(db_engine: Engine) -> sessionmaker[Session]:
    """테스트용 DB session factory를 제공한다."""
    return sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db_session(db_session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """테스트용 DB session fixture를 제공한다."""
    session = db_session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db_session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    """HTTP 통합 테스트 client를 제공한다."""
    def override_db_session() -> Iterator[Session]:
        """테스트 요청에 DB session을 주입한다."""
        session = db_session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_db_session
    original_factory = app.state.session_factory
    app.state.session_factory = db_session_factory
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.state.session_factory = original_factory
