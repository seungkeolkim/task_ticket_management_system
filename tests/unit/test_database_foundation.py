from datetime import datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.dialects import sqlite
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.db.engine import create_database_engine
from app.db.transaction import transaction_scope
from app.db.types import UTCDateTime
from app.models import Organization


def test_sql_parameters_are_hidden_in_logs_and_exceptions(caplog):
    engine = create_database_engine("sqlite://", echo=True)
    secret = "sensitive-authentication-parameter"
    try:
        with engine.connect() as connection:
            with pytest.raises(DBAPIError) as error:
                connection.execute(
                    text("INSERT INTO missing_table VALUES (:secret)"), {"secret": secret}
                )
        assert secret not in str(error.value)
        assert secret not in caplog.text
        assert "parameters hidden" in str(error.value)
    finally:
        engine.dispose()


def test_sqlite_foreign_keys_are_enabled(db_session: Session) -> None:
    assert db_session.scalar(text("PRAGMA foreign_keys")) == 1


def test_model_timestamps_are_returned_as_aware_utc(db_session: Session) -> None:
    organization = Organization(key="root", name="Root")
    db_session.add(organization)
    db_session.commit()
    db_session.refresh(organization)

    assert organization.created_at.utcoffset() is not None
    assert organization.created_at.utcoffset().total_seconds() == 0
    assert organization.updated_at.utcoffset() is not None
    assert organization.updated_at.utcoffset().total_seconds() == 0


def test_utc_datetime_rejects_naive_values() -> None:
    utc_type = UTCDateTime()

    with pytest.raises(ValueError, match="Naive datetime"):
        utc_type.process_bind_param(datetime(2026, 1, 1), sqlite.dialect())


def test_transaction_scope_commits_and_rolls_back(
    db_session_factory: sessionmaker[Session],
) -> None:
    with transaction_scope(db_session_factory) as session:
        session.add(Organization(key="committed", name="Committed"))

    with pytest.raises(RuntimeError, match="force rollback"):
        with transaction_scope(db_session_factory) as session:
            session.add(Organization(key="rolled-back", name="Rolled Back"))
            raise RuntimeError("force rollback")

    with db_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Organization)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(Organization)
                .where(Organization.key == "rolled-back")
            )
            == 0
        )
