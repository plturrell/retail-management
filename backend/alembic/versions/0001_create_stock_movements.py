"""create stock_movements

Revision ID: 0001
Revises:
Create Date: 2026-04-26

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_movements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("store_id", sa.String(length=36), nullable=False),
        sa.Column("sku_id", sa.String(length=36), nullable=False),
        sa.Column("inventory_type", sa.String(length=32), nullable=False, server_default="finished"),
        sa.Column("delta_qty", sa.Integer(), nullable=False),
        sa.Column("resulting_qty", sa.Integer(), nullable=True),
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("reference_type", sa.String(length=64), nullable=True),
        sa.Column("reference_id", sa.String(length=36), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "event_time",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stock_movements_store_id", "stock_movements", ["store_id"])
    op.create_index("ix_stock_movements_sku_id", "stock_movements", ["sku_id"])
    op.create_index("ix_stock_movements_actor_user_id", "stock_movements", ["actor_user_id"])
    op.create_index(
        "ix_stock_movements_store_sku_event",
        "stock_movements",
        ["store_id", "sku_id", "event_time"],
    )
    op.create_index(
        "ix_stock_movements_store_event",
        "stock_movements",
        ["store_id", "event_time"],
    )


def downgrade() -> None:
    op.drop_index("ix_stock_movements_store_event", table_name="stock_movements")
    op.drop_index("ix_stock_movements_store_sku_event", table_name="stock_movements")
    op.drop_index("ix_stock_movements_actor_user_id", table_name="stock_movements")
    op.drop_index("ix_stock_movements_sku_id", table_name="stock_movements")
    op.drop_index("ix_stock_movements_store_id", table_name="stock_movements")
    op.drop_table("stock_movements")
