"""Add salesperson attribution: salesperson_aliases table and orders.salesperson_id

Revision ID: 008
Revises: 007
Create Date: 2026-04-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add salesperson_id column to orders
    with op.batch_alter_table("orders") as batch_op:
        batch_op.add_column(
            sa.Column("salesperson_id", sa.UUID(), nullable=True),
        )
        batch_op.create_foreign_key(
            "fk_orders_salesperson_id",
            "users",
            ["salesperson_id"],
            ["id"],
        )

    # Create salesperson_aliases table
    op.create_table(
        "salesperson_aliases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("alias_name", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("store_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("salesperson_aliases")
    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_constraint("fk_orders_salesperson_id", type_="foreignkey")
        batch_op.drop_column("salesperson_id")
