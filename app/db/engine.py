from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, event


def create_database_engine(
    database_url: str,
    *,
    echo: bool = False,
    pool_pre_ping: bool = True,
    **engine_options: Any,
) -> Engine:
    """DB engine 생성을 처리한다."""
    options: dict[str, Any] = {
        "echo": echo,
        "pool_pre_ping": pool_pre_ping,
        "hide_parameters": True,
        **engine_options,
    }
    if database_url.startswith("sqlite"):
        connect_args = dict(options.pop("connect_args", {}))
        connect_args.setdefault("check_same_thread", False)
        options["connect_args"] = connect_args

    engine = create_engine(database_url, **options)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection: Any, _: Any) -> None:
            """sqlite foreign keys 활성화한다."""
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine
