"""Initial schema — all Phase 1 tables

Revision ID: 001
Revises:
Create Date: 2026-04-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Enums ---
    role_enum = sa.Enum("owner", "manager", "staff", name="role_enum")
    role_enum.create(op.get_bind(), checkfirst=True)

    order_status_enum = sa.Enum("open", "completed", "voided", name="order_status_enum")
    order_status_enum.create(op.get_bind(), checkfirst=True)

    order_source_enum = sa.Enum(
        "nec_pos", "hipay", "airwallex", "shopify", "manual", name="order_source_enum"
    )
    order_source_enum.create(op.get_bind(), checkfirst=True)

    # --- stores ---
    op.create_table(
        "stores",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("location", sa.String(255), nullable=False),
        sa.Column("address", sa.String(500), nullable=False),
        sa.Column("business_hours_start", sa.Time(), nullable=False),
        sa.Column("business_hours_end", sa.Time(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("firebase_uid", sa.String(128), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_firebase_uid", "users", ["firebase_uid"])

    # --- user_store_roles ---
    op.create_table(
        "user_store_roles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", role_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "store_id", name="uq_user_store"),
    )

    # --- brands ---
    op.create_table(
        "brands",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category_type", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # --- categories ---
    op.create_table(
        "categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("parent_id", UUID(as_uuid=True), sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("catg_code", sa.String(50), nullable=False),
        sa.Column("cag_catg_code", sa.String(50), nullable=True),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # --- skus ---
    op.create_table(
        "skus",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("sku_code", sa.String(16), nullable=False, unique=True),
        sa.Column("description", sa.String(60), nullable=False),
        sa.Column("long_description", sa.String(1000), nullable=True),
        sa.Column("cost_price", sa.Numeric(20, 2), nullable=True),
        sa.Column("category_id", UUID(as_uuid=True), sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("brand_id", UUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=True),
        sa.Column("tax_code", sa.String(1), nullable=False, server_default="G"),
        sa.Column("gender", sa.String(20), nullable=True),
        sa.Column("age_group", sa.String(20), nullable=True),
        sa.Column("is_unique_piece", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("use_stock", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("block_sales", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_skus_sku_code", "skus", ["sku_code"])

    # --- plus (PLU / barcodes) ---
    op.create_table(
        "plus",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("plu_code", sa.String(20), nullable=False, unique=True),
        sa.Column("sku_id", UUID(as_uuid=True), sa.ForeignKey("skus.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_plus_plu_code", "plus", ["plu_code"])

    # --- prices ---
    op.create_table(
        "prices",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("sku_id", UUID(as_uuid=True), sa.ForeignKey("skus.id", ondelete="CASCADE"), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=True),
        sa.Column("price_incl_tax", sa.Numeric(20, 2), nullable=False),
        sa.Column("price_excl_tax", sa.Numeric(20, 2), nullable=False),
        sa.Column("price_unit", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # --- promotions ---
    op.create_table(
        "promotions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("disc_id", sa.String(20), nullable=False),
        sa.Column("sku_id", UUID(as_uuid=True), sa.ForeignKey("skus.id", ondelete="CASCADE"), nullable=True),
        sa.Column("category_id", UUID(as_uuid=True), sa.ForeignKey("categories.id", ondelete="CASCADE"), nullable=True),
        sa.Column("line_type", sa.String(20), nullable=False),
        sa.Column("disc_method", sa.String(20), nullable=False),
        sa.Column("disc_value", sa.Numeric(11, 2), nullable=False),
        sa.Column("line_group", sa.String(1), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # --- inventories ---
    op.create_table(
        "inventories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("sku_id", UUID(as_uuid=True), sa.ForeignKey("skus.id", ondelete="CASCADE"), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("qty_on_hand", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reorder_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reorder_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("serial_number", sa.String(255), nullable=True),
        sa.Column("last_updated", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # --- orders ---
    op.create_table(
        "orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("order_number", sa.String(50), nullable=False, unique=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("staff_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("order_date", sa.DateTime(), nullable=False),
        sa.Column("subtotal", sa.Numeric(20, 2), nullable=False),
        sa.Column("discount_total", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("tax_total", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("grand_total", sa.Numeric(20, 2), nullable=False),
        sa.Column("payment_method", sa.String(50), nullable=False),
        sa.Column("payment_ref", sa.String(255), nullable=True),
        sa.Column("status", order_status_enum, nullable=False),
        sa.Column("source", order_source_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # --- order_items ---
    op.create_table(
        "order_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sku_id", UUID(as_uuid=True), sa.ForeignKey("skus.id"), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(20, 2), nullable=False),
        sa.Column("discount", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("line_total", sa.Numeric(20, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("inventories")
    op.drop_table("promotions")
    op.drop_table("prices")
    op.drop_table("plus")
    op.drop_table("skus")
    op.drop_table("categories")
    op.drop_table("brands")
    op.drop_table("user_store_roles")
    op.drop_table("users")
    op.drop_table("stores")

    sa.Enum(name="order_source_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="order_status_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="role_enum").drop(op.get_bind(), checkfirst=True)
