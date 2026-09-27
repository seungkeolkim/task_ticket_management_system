"""Add one-level comment replies.

Revision ID: 20260927_0005
Revises: 20260926_0004
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260927_0005"
down_revision: str | None = "20260926_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_sqlite_comment_reference_constraints() -> None:
    """SQLite comments table 재구성 전에 외부 comment FK를 임시 제거한다."""
    if op.get_bind().dialect.name != "sqlite":
        return
    with op.batch_alter_table("mentions") as batch_operation:
        batch_operation.drop_constraint("fk_mentions_comment", type_="foreignkey")
    with op.batch_alter_table("attachments") as batch_operation:
        batch_operation.drop_constraint("fk_attachments_comment", type_="foreignkey")


def _restore_sqlite_comment_reference_constraints() -> None:
    """SQLite comments table 재구성 뒤 외부 comment FK를 복원한다."""
    if op.get_bind().dialect.name != "sqlite":
        return
    with op.batch_alter_table("mentions") as batch_operation:
        batch_operation.create_foreign_key(
            "fk_mentions_comment",
            "comments",
            ["project_id", "ticket_id", "comment_id"],
            ["project_id", "ticket_id", "id"],
            ondelete="CASCADE",
        )
    with op.batch_alter_table("attachments") as batch_operation:
        batch_operation.create_foreign_key(
            "fk_attachments_comment",
            "comments",
            ["project_id", "ticket_id", "comment_id"],
            ["project_id", "ticket_id", "id"],
            ondelete="RESTRICT",
        )


def upgrade() -> None:
    """댓글에 같은 티켓의 원댓글을 참조하는 부모 관계를 추가한다."""
    _drop_sqlite_comment_reference_constraints()
    with op.batch_alter_table("comments") as batch_operation:
        batch_operation.add_column(sa.Column("parent_comment_id", sa.Integer(), nullable=True))
        batch_operation.create_foreign_key(
            "fk_comments_parent",
            "comments",
            ["project_id", "ticket_id", "parent_comment_id"],
            ["project_id", "ticket_id", "id"],
            ondelete="RESTRICT",
        )
        batch_operation.create_check_constraint(
            op.f("ck_comments_not_own_parent"),
            "parent_comment_id IS NULL OR parent_comment_id != id",
        )
        batch_operation.create_index(
            "ix_comments_parent_created",
            ["parent_comment_id", "created_at", "id"],
            unique=False,
        )
    _restore_sqlite_comment_reference_constraints()


def downgrade() -> None:
    """대댓글 부모 관계와 관련 제약 및 index를 제거한다."""
    _drop_sqlite_comment_reference_constraints()
    op.execute(sa.text("UPDATE comments SET parent_comment_id = NULL"))
    with op.batch_alter_table("comments") as batch_operation:
        batch_operation.drop_index("ix_comments_parent_created")
        batch_operation.drop_constraint(
            op.f("ck_comments_not_own_parent"),
            type_="check",
        )
        batch_operation.drop_constraint("fk_comments_parent", type_="foreignkey")
        batch_operation.drop_column("parent_comment_id")
    _restore_sqlite_comment_reference_constraints()
