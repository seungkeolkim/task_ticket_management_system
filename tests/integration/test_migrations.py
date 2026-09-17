import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.engine import create_database_engine
from app.models import Organization, Project, Ticket, User

DOMAIN_TABLES = {"organizations", "users", "user_sessions", "audit_logs"}
MVP_TABLES = {
    "projects",
    "project_members",
    "tickets",
    "ticket_deletion_batches",
    "ticket_relations",
    "ticket_history",
    "comments",
    "mentions",
    "attachments",
    "saved_filters",
    "report_skills",
    "report_skill_versions",
    "report_runs",
    "report_run_projects",
    "report_attempts",
}


def test_upgrade_creates_identity_schema(
    alembic_config: Config,
    migrated_database_url: str,
) -> None:
    engine = create_engine(migrated_database_url)
    try:
        assert DOMAIN_TABLES | MVP_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_downgrade_removes_identity_schema(
    alembic_config: Config,
    migrated_database_url: str,
) -> None:
    command.downgrade(alembic_config, "base")
    engine = create_engine(migrated_database_url)
    try:
        assert (DOMAIN_TABLES | MVP_TABLES).isdisjoint(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_migration_matches_model_metadata(
    alembic_config: Config,
    migrated_database_url: str,
) -> None:
    command.check(alembic_config)


def test_migrated_checks_match_models(migrated_database_url: str) -> None:
    # Alembic check does not detect every CHECK constraint difference.
    engine = create_database_engine(migrated_database_url)
    try:
        inspector = inspect(engine)
        for name in MVP_TABLES:
            expected = {
                c.name: " ".join(str(c.sqltext).split())
                for c in Base.metadata.tables[name].constraints
                if hasattr(c, "sqltext")
            }
            actual = {
                c["name"]: " ".join(c["sqltext"].split())
                for c in inspector.get_check_constraints(name)
            }
            assert actual == expected, name
    finally:
        engine.dispose()


def test_populated_upgrade_downgrade_preserves_identity(
    alembic_config: Config, database_url: str
) -> None:
    command.upgrade(alembic_config, "20260916_0001")
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as session:
            org = Organization(key="engineering", name="개발")
            session.add(org)
            session.flush()
            user = User(
                login_id="existing",
                display_name="기존 사용자",
                password_hash="unchanged",
                organization_id=org.id,
            )
            session.add(user)
            session.commit()
            user_id = user.id
        command.upgrade(alembic_config, "head")
        command.check(alembic_config)
        with Session(engine) as session:
            assert session.get(User, user_id).password_hash == "unchanged"
            project = Project(key="DEV", name="개발", created_by_id=user_id)
            session.add(project)
            session.flush()
            epic = Ticket(
                project_id=project.id,
                number=1,
                key="DEV-1",
                type="EPIC",
                title="에픽",
                creator_id=user_id,
            )
            session.add(epic)
            session.flush()
            session.add(
                Ticket(
                    project_id=project.id,
                    number=2,
                    key="DEV-2",
                    parent_id=epic.id,
                    title="하위 작업",
                    creator_id=user_id,
                )
            )
            session.commit()
        command.downgrade(alembic_config, "20260916_0001")
        assert MVP_TABLES.isdisjoint(inspect(engine).get_table_names())
        with Session(engine) as session:
            assert session.get(User, user_id).display_name == "기존 사용자"
            assert session.get(Organization, 1).name == "개발"
        command.upgrade(alembic_config, "head")
        command.check(alembic_config)
    finally:
        engine.dispose()


def test_duplicate_organizations_fail_before_schema_changes(
    alembic_config: Config, database_url: str
) -> None:
    command.upgrade(alembic_config, "20260916_0001")
    engine = create_database_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO organizations (key, name) "
                    "VALUES ('a', 'duplicate'), ('b', 'duplicate')"
                )
            )
        with pytest.raises(RuntimeError, match="Duplicate sibling"):
            command.upgrade(alembic_config, "head")
        assert MVP_TABLES.isdisjoint(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM organizations")) == 2
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260916_0001"
            )
    finally:
        engine.dispose()
