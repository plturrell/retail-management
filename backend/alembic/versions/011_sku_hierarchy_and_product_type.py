"""Expand sku_code to varchar(32), add product_type and attributes.

Revision ID: 011
Revises: 010

Changes:
  - skus.sku_code: VARCHAR(16) → VARCHAR(32) to fit hierarchical codes like
    DEC-CRY-000001 as well as longer supplier codes during migration.
  - skus.product_type: new ENUM('finished','material','manufactured') — SKU-level
    classification (what the product IS). Complements inventory.inventory_type
    which is per-location stock state.
  - skus.attributes: new JSONB for structured material/size/color/dimensions.
  - skus.status: new VARCHAR(20) 'active' | 'draft' | 'discontinued'.
  - supplier_products.supplier_sku_code: index added for lookup.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN CREATE TYPE product_type_enum AS ENUM "
        "('finished', 'material', 'manufactured'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )

    op.alter_column(
        "skus",
        "sku_code",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
    )

    op.add_column(
        "skus",
        sa.Column(
            "product_type",
            sa.Enum("finished", "material", "manufactured",
                    name="product_type_enum", create_type=False),
            nullable=False,
            server_default="finished",
        ),
    )
    op.add_column(
        "skus",
        sa.Column("attributes", JSONB, nullable=True),
    )
    op.add_column(
        "skus",
        sa.Column("status", sa.String(length=20),
                  nullable=False, server_default="active"),
    )

    op.create_index(
        "ix_supplier_products_supplier_sku_code",
        "supplier_products",
        ["supplier_sku_code"],
    )


def downgrade() -> None:
    op.drop_index("ix_supplier_products_supplier_sku_code", table_name="supplier_products")
    op.drop_column("skus", "status")
    op.drop_column("skus", "attributes")
    op.drop_column("skus", "product_type")
    op.alter_column(
        "skus",
        "sku_code",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=False,
    )
    # keep enum type in place for safety
