"""Add core uniqueness constraints for inventory and schedules

Revision ID: 004
Revises: 003
Create Date: 2026-04-12
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("inventories") as batch_op:
        batch_op.create_unique_constraint(
            "uq_inventory_store_sku",
            ["store_id", "sku_id"],
        )

    with op.batch_alter_table("schedules") as batch_op:
        batch_op.create_unique_constraint(
            "uq_schedule_store_week_start",
            ["store_id", "week_start"],
        )


def downgrade() -> None:
    with op.batch_alter_table("schedules") as batch_op:
        batch_op.drop_constraint("uq_schedule_store_week_start", type_="unique")

    with op.batch_alter_table("inventories") as batch_op:
        batch_op.drop_constraint("uq_inventory_store_sku", type_="unique")
