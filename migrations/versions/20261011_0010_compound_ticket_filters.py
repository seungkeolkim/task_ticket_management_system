"""Remove disposable v1 saved filters and make v2 the storage default."""

import logging

import sqlalchemy as sa
from alembic import op

revision = "20261011_0010"
down_revision = "20261005_0009"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    """v1 티켓 저장 필터만 삭제하고 다른 업무 데이터와 v2 row는 보존한다."""
    deleted_rows = op.get_bind().execute(
        sa.text("DELETE FROM saved_filters WHERE schema_version = 1")
    )
    logger.info("ticket_filter_v1_removed count=%s", deleted_rows.rowcount)
    with op.batch_alter_table("saved_filters") as batch_operations:
        batch_operations.alter_column(
            "schema_version", existing_type=sa.Integer(), server_default="2"
        )


def downgrade() -> None:
    """구 계약으로 변환할 수 없는 v2 필터를 삭제하며 제거된 v1 데이터는 복원하지 않는다."""
    deleted_rows = op.get_bind().execute(
        sa.text("DELETE FROM saved_filters WHERE schema_version = 2")
    )
    logger.info("ticket_filter_v2_removed count=%s", deleted_rows.rowcount)
    with op.batch_alter_table("saved_filters") as batch_operations:
        batch_operations.alter_column(
            "schema_version", existing_type=sa.Integer(), server_default="1"
        )
