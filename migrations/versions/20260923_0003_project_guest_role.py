"""add project guest role

Revision ID: 20260923_0003
Revises: 20260917_0002
Create Date: 2026-09-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260923_0003"
down_revision: str | None = "20260917_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project_members", schema=None) as batch_op:
        batch_op.drop_constraint("role_allowed", type_="check")
        batch_op.create_check_constraint(
            "role_allowed",
            "role IN ('PROJECT_ADMIN', 'PROJECT_USER', 'PROJECT_GUEST')",
        )


def downgrade() -> None:
    # The previous schema has no read-only role. Removing guest memberships is
    # safer than silently promoting them to writable PROJECT_USER access.
    op.execute("DELETE FROM project_members WHERE role = 'PROJECT_GUEST'")
    with op.batch_alter_table("project_members", schema=None) as batch_op:
        batch_op.drop_constraint("role_allowed", type_="check")
        batch_op.create_check_constraint(
            "role_allowed", "role IN ('PROJECT_ADMIN', 'PROJECT_USER')"
        )
