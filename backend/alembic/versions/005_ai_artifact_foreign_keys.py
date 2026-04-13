"""Add foreign key constraints to AI artifact tables

Revision ID: 005
Revises: 004
Create Date: 2026-04-12
"""
from typing import Sequence, Union

from alembic import op


revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ai_invocations") as batch_op:
        batch_op.create_foreign_key(
            "fk_ai_invocations_store_id",
            "stores",
            ["store_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("ai_artifacts") as batch_op:
        batch_op.create_foreign_key(
            "fk_ai_artifacts_invocation_id",
            "ai_invocations",
            ["invocation_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_ai_artifacts_store_id",
            "stores",
            ["store_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_artifacts") as batch_op:
        batch_op.drop_constraint("fk_ai_artifacts_store_id", type_="foreignkey")
        batch_op.drop_constraint("fk_ai_artifacts_invocation_id", type_="foreignkey")

    with op.batch_alter_table("ai_invocations") as batch_op:
        batch_op.drop_constraint("fk_ai_invocations_store_id", type_="foreignkey")
