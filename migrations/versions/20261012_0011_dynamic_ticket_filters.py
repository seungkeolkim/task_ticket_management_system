"""Preserve fixed v2 saved filters as v3 without resolving dynamic rules."""

import json
import logging

import sqlalchemy as sa
from alembic import op

revision = "20261012_0011"
down_revision = "20261011_0010"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    """고정 조건·이름·수정 시각을 보존하면서 v3 계약으로 이관한다."""
    connection = op.get_bind()
    filters_table = sa.table(
        "saved_filters",
        sa.column("id", sa.Integer),
        sa.column("schema_version", sa.Integer),
        sa.column("definition", sa.JSON),
    )
    rows = connection.execute(
        sa.select(filters_table.c.id, filters_table.c.definition).where(
            filters_table.c.schema_version == 2
        )
    ).all()
    for row in rows:
        definition = dict(row.definition)
        definition["schema_version"] = 3
        connection.execute(
            filters_table.update()
            .where(filters_table.c.id == row.id)
            .values(schema_version=3, definition=definition)
        )
    with op.batch_alter_table("saved_filters") as batch_operations:
        batch_operations.alter_column(
            "schema_version", existing_type=sa.Integer(), server_default="3"
        )
    logger.info("ticket_filter_v3_migrated count=%s", len(rows))


def downgrade() -> None:
    """동적 규칙이 있으면 변경 전에 중단하고 고정 조건만 v2로 되돌린다."""
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, definition FROM saved_filters WHERE schema_version = 3")
    ).all()
    converted_rows = []
    for row in rows:
        definition = (
            json.loads(row.definition) if isinstance(row.definition, str) else dict(row.definition)
        )
        pending_groups = [definition.get("expression", {})]
        while pending_groups:
            group = pending_groups.pop()
            for child in group.get("children", []):
                if child.get("kind") == "group":
                    pending_groups.append(child)
                elif child.pop("rule", None) is not None:
                    raise RuntimeError(
                        "Dynamic filters prevent downgrade; preserve or remove them explicitly."
                    )
        definition["schema_version"] = 2
        converted_rows.append((row.id, definition))
    for identifier, definition in converted_rows:
        connection.execute(
            sa.text(
                "UPDATE saved_filters SET schema_version = 2, definition = :definition "
                "WHERE id = :id"
            ),
            {"id": identifier, "definition": json.dumps(definition, ensure_ascii=False)},
        )
    with op.batch_alter_table("saved_filters") as batch_operations:
        batch_operations.alter_column(
            "schema_version", existing_type=sa.Integer(), server_default="2"
        )
    logger.info("ticket_filter_v2_restored count=%s", len(converted_rows))
