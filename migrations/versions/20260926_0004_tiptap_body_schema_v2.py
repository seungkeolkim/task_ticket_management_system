"""Replace Markdown body columns with Tiptap JSON body schema v2.

Revision ID: 20260926_0004
Revises: 20260923_0003
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260926_0004"
down_revision: str | None = "20260923_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMPTY_BODY_DOCUMENT_JSON = '{"content":[{"type":"paragraph"}],"type":"doc"}'
BODY_TABLES = ("tickets", "comments", "ticket_history")


def _require_empty_body_tables(direction: str) -> None:
    """본문 계약을 손실 없이 교체할 수 있도록 관련 table의 zero-row 상태를 확인한다."""
    connection = op.get_bind()
    populated_tables = []
    for table_name in BODY_TABLES:
        row_count = connection.scalar(sa.text(f"SELECT COUNT(*) FROM {table_name}"))
        if row_count:
            populated_tables.append(f"{table_name}={row_count}")
    if populated_tables:
        table_summary = ", ".join(populated_tables)
        raise RuntimeError(
            f"Tiptap body schema {direction} requires empty body tables; {table_summary}. "
            "Back up the database and resolve the unexpected rows before retrying."
        )


def _discard_v2_ticket_data_for_downgrade() -> None:
    """v1로 표현할 수 없는 v2 티켓과 종속 데이터를 명시적으로 제거한다."""
    connection = op.get_bind()
    for table_name in (
        "mentions",
        "attachments",
        "comments",
        "ticket_relations",
        "ticket_history",
    ):
        connection.execute(sa.text(f"DELETE FROM {table_name}"))
    while connection.scalar(sa.text("SELECT COUNT(*) FROM tickets")):
        result = connection.execute(
            sa.text(
                "DELETE FROM tickets WHERE id NOT IN "
                "(SELECT parent_id FROM tickets WHERE parent_id IS NOT NULL)"
            )
        )
        if result.rowcount == 0:
            raise RuntimeError("Could not remove ticket hierarchy during destructive downgrade")
    connection.execute(sa.text("DELETE FROM ticket_deletion_batches"))


def upgrade() -> None:
    """빈 업무 table의 Markdown column을 Tiptap JSON v2 column으로 교체한다."""
    _require_empty_body_tables("upgrade")
    empty_document_default = sa.text(f"'{EMPTY_BODY_DOCUMENT_JSON}'")

    with op.batch_alter_table("tickets") as batch_operation:
        batch_operation.drop_constraint("positive_body_version", type_="check")
        batch_operation.drop_column("description")
        batch_operation.add_column(
            sa.Column(
                "description_document",
                sa.JSON(),
                server_default=empty_document_default,
                nullable=False,
            )
        )
        batch_operation.alter_column(
            "body_schema_version",
            existing_type=sa.Integer(),
            server_default="2",
            existing_nullable=False,
        )
        batch_operation.create_check_constraint(
            "supported_body_version", "body_schema_version = 2"
        )

    with op.batch_alter_table("comments") as batch_operation:
        batch_operation.drop_constraint("positive_versions", type_="check")
        batch_operation.drop_column("body")
        batch_operation.add_column(
            sa.Column(
                "body_document",
                sa.JSON(),
                server_default=empty_document_default,
                nullable=False,
            )
        )
        batch_operation.alter_column(
            "body_schema_version",
            existing_type=sa.Integer(),
            server_default="2",
            existing_nullable=False,
        )
        batch_operation.create_check_constraint(
            "supported_body_version",
            "version > 0 AND body_schema_version = 2",
        )

    with op.batch_alter_table("ticket_history") as batch_operation:
        batch_operation.alter_column(
            "schema_version",
            existing_type=sa.Integer(),
            server_default="2",
            existing_nullable=False,
        )


def downgrade() -> None:
    """v2 업무 데이터를 폐기하고 Markdown v1 구조로 되돌린다.

    JSON 본문은 Markdown으로 변환하지 않으며 ticket·comment·history와 종속 데이터를
    제거한다. 배포 rollback 전에는 반드시 일관된 DB·첨부파일 백업을 확보해야 한다.
    """
    _discard_v2_ticket_data_for_downgrade()

    with op.batch_alter_table("ticket_history") as batch_operation:
        batch_operation.alter_column(
            "schema_version",
            existing_type=sa.Integer(),
            server_default="1",
            existing_nullable=False,
        )

    with op.batch_alter_table("comments") as batch_operation:
        batch_operation.drop_constraint(
            "supported_body_version", type_="check"
        )
        batch_operation.drop_column("body_document")
        batch_operation.add_column(
            sa.Column("body", sa.Text(), server_default="", nullable=False)
        )
        batch_operation.alter_column(
            "body_schema_version",
            existing_type=sa.Integer(),
            server_default="1",
            existing_nullable=False,
        )
        batch_operation.create_check_constraint(
            "positive_versions", "version > 0 AND body_schema_version > 0"
        )

    with op.batch_alter_table("comments") as batch_operation:
        batch_operation.alter_column(
            "body", existing_type=sa.Text(), server_default=None, existing_nullable=False
        )

    with op.batch_alter_table("tickets") as batch_operation:
        batch_operation.drop_constraint(
            "supported_body_version", type_="check"
        )
        batch_operation.drop_column("description_document")
        batch_operation.add_column(
            sa.Column("description", sa.Text(), server_default="", nullable=False)
        )
        batch_operation.alter_column(
            "body_schema_version",
            existing_type=sa.Integer(),
            server_default="1",
            existing_nullable=False,
        )
        batch_operation.create_check_constraint(
            "positive_body_version", "body_schema_version > 0"
        )
