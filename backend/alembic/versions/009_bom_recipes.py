"""Add BOM recipe tables

Revision ID: 009
Revises: 008
Create Date: 2026-04-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bom_recipes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("finished_sku_id", sa.Uuid(), sa.ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_bom_recipes_store_id", "bom_recipes", ["store_id"])

    op.create_table(
        "bom_recipe_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("recipe_id", sa.Uuid(), sa.ForeignKey("bom_recipes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sku_id", sa.Uuid(), sa.ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantity_required", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_bom_recipe_items_recipe_id", "bom_recipe_items", ["recipe_id"])


def downgrade() -> None:
    op.drop_table("bom_recipe_items")
    op.drop_table("bom_recipes")
