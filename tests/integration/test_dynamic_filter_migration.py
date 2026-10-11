"""v2 필터 보존과 동적 규칙이 있는 downgrade의 원자적 중단을 검증한다."""

import json

import pytest
from alembic import command
from sqlalchemy import inspect, text

from app.db.engine import create_database_engine


@pytest.fixture
def populated_filter_database(alembic_config, database_url):
    """v2 개인·공유 필터와 업무 row가 있는 임시 DB를 준비한다."""
    command.upgrade(alembic_config, "20261011_0010")
    engine = create_database_engine(database_url)
    definition = {
        "schema_version": 2,
        "expression": {
            "kind": "group",
            "operator": "OR",
            "children": [
                {
                    "kind": "group",
                    "operator": "AND",
                    "negated": True,
                    "children": [
                        {
                            "kind": "condition",
                            "field": "assignee",
                            "operator": "in",
                            "values": [1],
                            "negated": False,
                        }
                    ],
                }
            ],
            "negated": False,
        },
        "sort_by": "number",
        "sort_direction": "asc",
        "page_size": 10,
    }
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO organizations (key, name) VALUES ('org', '조직')"))
        connection.execute(
            text(
                "INSERT INTO users (login_id, display_name, password_hash, organization_id) "
                "VALUES ('member', '사용자', 'hash', 1)"
            )
        )
        connection.execute(
            text("INSERT INTO projects (key, name, created_by_id) VALUES ('DEV', '개발', 1)")
        )
        connection.execute(
            text(
                "INSERT INTO tickets (project_id, number, key, title, creator_id) "
                "VALUES (1, 1, 'DEV-1', '보존할 업무', 1)"
            )
        )
        for scope in ["PERSONAL", "PROJECT"]:
            connection.execute(
                text(
                    "INSERT INTO saved_filters "
                    "(project_id, owner_id, name, visibility, schema_version, definition) "
                    "VALUES (1, 1, :scope, :scope, 2, :definition)"
                ),
                {"scope": scope, "definition": json.dumps(definition)},
            )
    try:
        yield engine, definition
    finally:
        engine.dispose()


def test_dynamic_filter_migration_preserves_fixed_conditions_and_metadata(
    alembic_config, populated_filter_database
):
    """조건·정렬·row ID·이름·공개 범위·시각·업무 데이터를 upgrade/downgrade에서 보존한다."""
    engine, original_definition = populated_filter_database
    with engine.connect() as connection:
        original_rows = connection.execute(
            text(
                "SELECT id, name, visibility, owner_id, created_at, updated_at "
                "FROM saved_filters ORDER BY id"
            )
        ).all()
        original_tickets = connection.execute(text("SELECT * FROM tickets")).all()
    command.upgrade(alembic_config, "head")
    command.check(alembic_config)
    with engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT id, name, visibility, owner_id, created_at, updated_at "
                    "FROM saved_filters ORDER BY id"
                )
            ).all()
            == original_rows
        )
        definitions = connection.execute(
            text("SELECT schema_version, definition FROM saved_filters")
        ).all()
        for version, serialized_definition in definitions:
            assert version == 3
            assert json.loads(serialized_definition) == original_definition | {"schema_version": 3}
        assert connection.execute(text("SELECT * FROM tickets")).all() == original_tickets
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    command.downgrade(alembic_config, "20261011_0010")
    with engine.connect() as connection:
        for version, serialized_definition in connection.execute(
            text("SELECT schema_version, definition FROM saved_filters")
        ):
            assert version == 2 and json.loads(serialized_definition) == original_definition
    default_column = next(
        column
        for column in inspect(engine).get_columns("saved_filters")
        if column["name"] == "schema_version"
    )
    assert "2" in default_column["default"]


def test_dynamic_filter_downgrade_stops_before_any_row_or_schema_change(
    alembic_config, populated_filter_database
):
    """동적 필터가 뒤에 있어도 앞선 고정 필터를 먼저 변환하거나 규칙을 고정하지 않는다."""
    engine, definition = populated_filter_database
    command.upgrade(alembic_config, "head")
    dynamic_definition = definition | {
        "schema_version": 3,
        "expression": {
            "children": [
                {
                    "kind": "condition",
                    "field": "creator",
                    "operator": "in",
                    "values": [],
                    "rule": {"kind": "current_user"},
                }
            ]
        },
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO saved_filters "
                "(project_id, owner_id, name, visibility, schema_version, definition) "
                "VALUES (1, 1, '동적', 'PERSONAL', 3, :definition)"
            ),
            {"definition": json.dumps(dynamic_definition)},
        )
        before = connection.execute(text("SELECT * FROM saved_filters ORDER BY id")).all()
    with pytest.raises(RuntimeError, match="Dynamic filters prevent downgrade"):
        command.downgrade(alembic_config, "20261011_0010")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT * FROM saved_filters ORDER BY id")).all() == before
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261012_0011"
