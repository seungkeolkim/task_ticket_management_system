"""Preserve v3 saved rules as v4 with independent date anchors."""

import logging

import sqlalchemy as sa
from alembic import op

revision = "20261012_0012"
down_revision = "20261012_0011"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def migrate_filter_versions(source_version: int, target_version: int) -> None:
    """전체 row를 먼저 검사한 뒤 조건·메타데이터를 보존하며 저장 version만 변경한다."""
    connection = op.get_bind()
    filters_table = sa.table(
        "saved_filters",
        sa.column("id", sa.Integer),
        sa.column("schema_version", sa.Integer),
        sa.column("definition", sa.JSON),
    )
    rows = connection.execute(
        sa.select(filters_table.c.id, filters_table.c.definition).where(
            filters_table.c.schema_version == source_version
        )
    ).all()
    converted_rows = []
    for row in rows:
        definition = dict(row.definition)
        if target_version == 3:
            pending_groups = [definition.get("expression", {})]
            while pending_groups:
                group = pending_groups.pop()
                for child in group.get("children", []):
                    if child.get("kind") == "group":
                        pending_groups.append(child)
                    elif (child.get("rule") or {}).get("kind") in {"week_day", "date_range"}:
                        raise RuntimeError(
                            "Date anchors prevent downgrade; preserve or remove them explicitly."
                        )
        definition["schema_version"] = target_version
        converted_rows.append((row.id, definition))
    for identifier, definition in converted_rows:
        connection.execute(
            filters_table.update()
            .where(filters_table.c.id == identifier)
            .values(schema_version=target_version, definition=definition)
        )
    with op.batch_alter_table("saved_filters") as batch_operations:
        batch_operations.alter_column(
            "schema_version", existing_type=sa.Integer(), server_default=str(target_version)
        )
    logger.info(
        "ticket_filter_version_changed source=%s target=%s count=%s",
        source_version,
        target_version,
        len(rows),
    )


def upgrade() -> None:
    """기존 v3 고정값과 동적 규칙을 보존하며 v4로 이관한다."""
    migrate_filter_versions(3, 4)


def downgrade() -> None:
    """새 날짜 경계가 없으면 규칙을 보존하며 v3로 되돌린다."""
    migrate_filter_versions(4, 3)
