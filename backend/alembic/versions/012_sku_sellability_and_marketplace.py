"""Add sellability flags and marketplace identifiers to SKUs.

Revision ID: 012
Revises: 011

New columns on ``skus``:
  * form_factor            — VARCHAR(50)  e.g. Bracelet, Ring, Bowl, Vase.
                              Distinct from ``product_type`` (finished/material/
                              manufactured) which describes how the item is sourced.
  * sale_ready             — BOOLEAN     ``true`` when the item has enough info
                              (price, description, material) to be sold at POS.
                              This is the master gate for NEC POS export.
  * stocking_status        — VARCHAR(30) in_stock / to_order / in_production /
                              discontinued — workflow state, not location.
  * primary_stocking_location — VARCHAR(40) preferred retail location tag
                              (jewel / takashimaya / breeze / online).
  * amazon_sku             — VARCHAR(50)  Amazon ASIN / seller SKU
  * google_product_id      — VARCHAR(100) Google Merchant feed identifier
  * google_product_category — VARCHAR(255) Google taxonomy path
  * legacy_code            — VARCHAR(50)  our previous internal code (A448-style),
                              kept for traceability.
"""
from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("skus", sa.Column("form_factor", sa.String(length=50), nullable=True))
    op.add_column(
        "skus",
        sa.Column("sale_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("skus", sa.Column("stocking_status", sa.String(length=30), nullable=True))
    op.add_column("skus", sa.Column("primary_stocking_location", sa.String(length=40), nullable=True))
    op.add_column("skus", sa.Column("amazon_sku", sa.String(length=50), nullable=True))
    op.add_column("skus", sa.Column("google_product_id", sa.String(length=100), nullable=True))
    op.add_column("skus", sa.Column("google_product_category", sa.String(length=255), nullable=True))
    op.add_column("skus", sa.Column("legacy_code", sa.String(length=50), nullable=True))

    op.create_index("ix_skus_form_factor", "skus", ["form_factor"])
    op.create_index("ix_skus_sale_ready", "skus", ["sale_ready"])
    op.create_index("ix_skus_legacy_code", "skus", ["legacy_code"])


def downgrade() -> None:
    op.drop_index("ix_skus_legacy_code", table_name="skus")
    op.drop_index("ix_skus_sale_ready", table_name="skus")
    op.drop_index("ix_skus_form_factor", table_name="skus")
    op.drop_column("skus", "legacy_code")
    op.drop_column("skus", "google_product_category")
    op.drop_column("skus", "google_product_id")
    op.drop_column("skus", "amazon_sku")
    op.drop_column("skus", "primary_stocking_location")
    op.drop_column("skus", "stocking_status")
    op.drop_column("skus", "sale_ready")
    op.drop_column("skus", "form_factor")
