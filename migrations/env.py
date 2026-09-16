from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool

import app.models  # noqa: F401
from app.core.config import ensure_data_directories, get_settings
from app.db.base import Base
from app.db.engine import create_database_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
ensure_data_directories(settings)
migration_database_url = config.attributes.get("database_url", settings.database_url)
config.set_main_option("sqlalchemy.url", migration_database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=migration_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=migration_database_url.startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_database_engine(
        migration_database_url,
        echo=False,
        pool_pre_ping=True,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=migration_database_url.startswith("sqlite"),
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
