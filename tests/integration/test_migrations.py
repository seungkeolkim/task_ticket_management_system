from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

DOMAIN_TABLES = {"organizations", "users", "user_sessions", "audit_logs"}


def test_upgrade_creates_identity_schema(
    alembic_config: Config,
    migrated_database_url: str,
) -> None:
    engine = create_engine(migrated_database_url)
    try:
        assert DOMAIN_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_downgrade_removes_identity_schema(
    alembic_config: Config,
    migrated_database_url: str,
) -> None:
    command.downgrade(alembic_config, "base")
    engine = create_engine(migrated_database_url)
    try:
        assert DOMAIN_TABLES.isdisjoint(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_migration_matches_model_metadata(
    alembic_config: Config,
    migrated_database_url: str,
) -> None:
    command.check(alembic_config)
