"""v3 규칙의 무손실 이관과 신규 날짜 경계 downgrade 중단을 검증한다."""

import json

import pytest
from alembic import command
from sqlalchemy import text
from test_dynamic_filter_migration import populated_filter_database as populated_filter_database


def test_anchor_migration_preserves_existing_dynamic_rules_and_metadata(
    alembic_config, populated_filter_database
):
    """v3 고정·현재 사용자 규칙 및 메타데이터를 upgrade/downgrade에서 보존한다."""
    engine, definition = populated_filter_database
    command.upgrade(alembic_config, "20261012_0011")
    current_user = definition | {
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
                "VALUES (1, 1, '현재 사용자', 'PROJECT', 3, :definition)"
            ),
            {"definition": json.dumps(current_user)},
        )
        original_rows = (
            connection.execute(text("SELECT * FROM saved_filters ORDER BY id")).mappings().all()
        )
    command.upgrade(alembic_config, "head")
    command.check(alembic_config)
    with engine.connect() as connection:
        upgraded = (
            connection.execute(text("SELECT * FROM saved_filters ORDER BY id")).mappings().all()
        )
        for before, after in zip(original_rows, upgraded, strict=True):
            assert after["schema_version"] == 4
            assert json.loads(after["definition"]) == json.loads(before["definition"]) | {
                "schema_version": 4
            }
            for column in before:
                if column not in {"schema_version", "definition"}:
                    assert after[column] == before[column]
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    command.downgrade(alembic_config, "20261012_0011")
    with engine.connect() as connection:
        restored = (
            connection.execute(text("SELECT * FROM saved_filters ORDER BY id")).mappings().all()
        )
        for before, after in zip(original_rows, restored, strict=True):
            assert json.loads(after["definition"]) == json.loads(before["definition"])
            assert after["schema_version"] == 3


@pytest.mark.parametrize(
    "rule",
    [
        {"kind": "week_day", "week": "last", "weekday": 4},
        {
            "kind": "date_range",
            "start": {"kind": "week_day", "week": "last", "weekday": 0},
            "end": {"kind": "week_day", "week": "last", "weekday": 4},
        },
    ],
)
def test_anchor_migration_downgrade_preflight_preserves_every_row(
    alembic_config, populated_filter_database, rule
):
    """신규 규칙이 있으면 앞선 고정 row나 schema도 변경하지 않는다."""
    engine, definition = populated_filter_database
    command.upgrade(alembic_config, "head")
    payload = definition | {
        "schema_version": 4,
        "expression": {
            "children": [
                {
                    "kind": "condition",
                    "field": "due_date",
                    "operator": "between" if rule["kind"] == "date_range" else "on",
                    "rule": rule,
                }
            ]
        },
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO saved_filters "
                "(project_id, owner_id, name, visibility, schema_version, definition) "
                "VALUES (1, 1, '요일 경계', 'PERSONAL', 4, :definition)"
            ),
            {"definition": json.dumps(payload)},
        )
        original = connection.execute(text("SELECT * FROM saved_filters ORDER BY id")).all()
    with pytest.raises(RuntimeError, match="Date anchors prevent downgrade"):
        command.downgrade(alembic_config, "20261012_0011")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT * FROM saved_filters ORDER BY id")).all() == original
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261012_0012"
