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


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    database_path = (tmp_path / "test.db").as_posix()
    return f"sqlite:///{database_path}"


@pytest.fixture
def alembic_config(database_url: str) -> Config:
    config = Config("alembic.ini")
    config.attributes["database_url"] = database_url
    return config


@pytest.fixture
def migrated_database_url(alembic_config: Config, database_url: str) -> Iterator[str]:
    command.upgrade(alembic_config, "head")
    yield database_url
    command.downgrade(alembic_config, "base")


@pytest.fixture
def db_engine(migrated_database_url: str) -> Iterator[Engine]:
    engine = create_database_engine(migrated_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session_factory(db_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db_session(db_session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = db_session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db_session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    def override_db_session() -> Iterator[Session]:
        session = db_session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_db_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
