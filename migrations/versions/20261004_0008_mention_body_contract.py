"""Allow v3 mention documents while preserving v2 content and history."""

import sqlalchemy as sa
from alembic import op

revision = "20261004_0008"
down_revision = "20261003_0007"
branch_labels = None
depends_on = None


def _convert_mentions_to_text(value):
    """downgrade 시 멘션의 표시 문자열을 보존하고 v2 본문으로 변환한다."""
    if isinstance(value, list):
        return [_convert_mentions_to_text(item) for item in value]
    if not isinstance(value, dict):
        return value
    if value.get("type") == "mention":
        return {"type": "text", "text": "@" + value["attrs"]["label"]}
    converted = {}
    for key, item in value.items():
        converted[key] = (
            2 if key == "body_schema_version" and item == 3 else _convert_mentions_to_text(item)
        )
    return converted


def _downgrade_documents() -> None:
    """현재 본문과 이력에서 v3 node를 일반 text로 변환한다."""
    connection = op.get_bind()
    for table_name, column_names in (
        ("tickets", ["description_document"]),
        ("comments", ["body_document"]),
        ("ticket_history", ["before_state", "after_state", "changes"]),
    ):
        columns = [sa.column("id", sa.Integer())]
        columns.extend(sa.column(name, sa.JSON()) for name in column_names)
        table = sa.table(table_name, *columns)
        for row in connection.execute(sa.select(table)).mappings():
            values = {}
            for column_name in column_names:
                original = row[column_name]
                converted = _convert_mentions_to_text(original)
                if converted != original:
                    values[column_name] = converted
            if values:
                connection.execute(table.update().where(table.c.id == row.id).values(**values))
    for table_name in ("tickets", "comments"):
        op.execute(
            sa.text(
                f"UPDATE {table_name} SET body_schema_version = 2 WHERE body_schema_version = 3"
            )
        )


def _replace_checks(allow_mentions: bool) -> None:
    """FK를 유지한 채 SQLite table 재구성으로 본문 version CHECK만 변경한다."""
    connection = op.get_bind()
    sqlite = connection.dialect.name == "sqlite"
    with op.get_context().autocommit_block():
        if sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            if not allow_mentions:
                _downgrade_documents()
            condition = (
                "body_schema_version IN (2, 3)" if allow_mentions else "body_schema_version = 2"
            )
            for table_name in ("tickets", "comments"):
                constraint_name = f"ck_{table_name}_supported_body_version"
                with op.batch_alter_table(table_name) as batch:
                    batch.drop_constraint(op.f(constraint_name), type_="check")
                    prefix = "version > 0 AND " if table_name == "comments" else ""
                    batch.create_check_constraint(op.f(constraint_name), prefix + condition)
            if sqlite and connection.exec_driver_sql("PRAGMA foreign_key_check").first():
                raise RuntimeError("Mention migration foreign key verification failed")
        finally:
            if sqlite:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")


def upgrade() -> None:
    """기존 데이터와 version을 보존하며 v3 저장을 허용한다."""
    _replace_checks(True)


def downgrade() -> None:
    """멘션 node의 사용자 참조 의미를 제거하고 표시 text와 원본 row를 보존한다."""
    _replace_checks(False)
