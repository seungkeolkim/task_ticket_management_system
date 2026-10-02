"""Add per-member project favorites.

Revision ID: 20260929_0006
Revises: 20260927_0005
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_0006"
down_revision: str | None = "20260927_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """프로젝트 참여 정보에 사용자별 즐겨찾기 상태를 추가한다."""
    with op.batch_alter_table("project_members") as batch_operation:
        batch_operation.add_column(
            sa.Column(
                "is_favorite",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )


def downgrade() -> None:
    """프로젝트 참여 정보에서 즐겨찾기 상태를 제거한다."""
    with op.batch_alter_table("project_members") as batch_operation:
        batch_operation.drop_column("is_favorite")
