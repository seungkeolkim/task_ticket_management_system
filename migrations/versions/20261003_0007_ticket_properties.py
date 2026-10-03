"""Add ticket-local labels and typed ad-hoc values without changing existing history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261003_0007"
down_revision: str | None = "20260929_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """기존 ticket을 빈 추가 속성 목록으로 확장한다."""
    op.add_column("tickets", sa.Column("labels", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column(
        "tickets", sa.Column("custom_fields", sa.JSON(), nullable=False, server_default="[]")
    )


def downgrade() -> None:
    """추가 속성의 현재 값을 제거하며 기존 ticket·이력은 보존한다."""
    op.drop_column("tickets", "custom_fields")
    op.drop_column("tickets", "labels")
