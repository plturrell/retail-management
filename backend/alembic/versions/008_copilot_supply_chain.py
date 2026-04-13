"""Add copilot & supply chain: inventory types, recommendations, work orders, transfers

Revision ID: 008
Revises: 007
Create Date: 2026-04-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. New enum types                                                    #
    # ------------------------------------------------------------------ #
    for stmt in [
        "DO $$ BEGIN CREATE TYPE inventory_type_enum AS ENUM ('purchased', 'material', 'finished'); EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        "DO $$ BEGIN CREATE TYPE sourcing_strategy_enum AS ENUM ('supplier_premade', 'manufactured_standard', 'manufactured_custom'); EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        "DO $$ BEGIN CREATE TYPE recommendation_type_enum AS ENUM ('reorder', 'price_change', 'stock_anomaly'); EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        "DO $$ BEGIN CREATE TYPE recommendation_status_enum AS ENUM ('pending', 'approved', 'rejected', 'applied', 'expired', 'queued', 'unavailable'); EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        "DO $$ BEGIN CREATE TYPE work_order_status_enum AS ENUM ('scheduled', 'in_progress', 'completed', 'cancelled'); EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        "DO $$ BEGIN CREATE TYPE stock_transfer_status_enum AS ENUM ('pending', 'in_transit', 'received', 'cancelled'); EXCEPTION WHEN duplicate_object THEN NULL; END $$",
    ]:
        op.execute(sa.text(stmt))

    # ------------------------------------------------------------------ #
    # 2. Extend inventories table                                          #
    # ------------------------------------------------------------------ #
    op.add_column(
        "inventories",
        sa.Column(
            "inventory_type",
            postgresql.ENUM("purchased", "material", "finished", name="inventory_type_enum", create_type=False),
            nullable=False,
            server_default="purchased",
        ),
    )
    op.add_column(
        "inventories",
        sa.Column(
            "sourcing_strategy",
            postgresql.ENUM("supplier_premade", "manufactured_standard", "manufactured_custom",
                            name="sourcing_strategy_enum", create_type=False),
            nullable=False,
            server_default="supplier_premade",
        ),
    )
    op.add_column(
        "inventories",
        sa.Column(
            "primary_supplier_id",
            sa.Uuid(),
            sa.ForeignKey("suppliers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # ------------------------------------------------------------------ #
    # 3. Inventory adjustment log                                          #
    # ------------------------------------------------------------------ #
    op.create_table(
        "inventory_adjustment_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("inventory_id", sa.Uuid(), sa.ForeignKey("inventories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sku_id", sa.Uuid(), sa.ForeignKey("skus.id", ondelete="CASCADE"), nullable=False),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quantity_delta", sa.Integer(), nullable=False),
        sa.Column("resulting_qty", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("source", sa.String(100), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_inv_adj_logs_inventory_id", "inventory_adjustment_logs", ["inventory_id"])
    op.create_index("ix_inv_adj_logs_store_id", "inventory_adjustment_logs", ["store_id"])

    # ------------------------------------------------------------------ #
    # 4. Manager recommendations                                           #
    # ------------------------------------------------------------------ #
    op.create_table(
        "manager_recommendations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sku_id", sa.Uuid(), sa.ForeignKey("skus.id", ondelete="SET NULL"), nullable=True),
        sa.Column("inventory_id", sa.Uuid(), sa.ForeignKey("inventories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("inventory_type", postgresql.ENUM("purchased", "material", "finished", name="inventory_type_enum", create_type=False), nullable=False, server_default="purchased"),
        sa.Column("sourcing_strategy", postgresql.ENUM("supplier_premade", "manufactured_standard", "manufactured_custom", name="sourcing_strategy_enum", create_type=False), nullable=False, server_default="supplier_premade"),
        sa.Column("supplier_name", sa.String(255), nullable=True),
        sa.Column("rec_type", postgresql.ENUM("reorder", "price_change", "stock_anomaly", name="recommendation_type_enum", create_type=False), nullable=False),
        sa.Column("status", postgresql.ENUM("pending", "approved", "rejected", "applied", "expired", "queued", "unavailable", name="recommendation_status_enum", create_type=False), nullable=False, server_default="pending"),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("0.8")),
        sa.Column("supporting_metrics", postgresql.JSONB(), nullable=True),
        sa.Column("source", sa.String(100), nullable=False, server_default=sa.text("'rules_engine'")),
        sa.Column("expected_impact", sa.Text(), nullable=True),
        sa.Column("current_price", sa.Numeric(20, 2), nullable=True),
        sa.Column("suggested_price", sa.Numeric(20, 2), nullable=True),
        sa.Column("suggested_order_qty", sa.Integer(), nullable=True),
        sa.Column("workflow_action", sa.String(50), nullable=True),
        sa.Column("analysis_status", sa.String(50), nullable=False, server_default=sa.text("'complete'")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_manager_rec_store_id", "manager_recommendations", ["store_id"])
    op.create_index("ix_manager_rec_status", "manager_recommendations", ["status"])

    # ------------------------------------------------------------------ #
    # 5. Work orders                                                       #
    # ------------------------------------------------------------------ #
    op.create_table(
        "work_orders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("finished_sku_id", sa.Uuid(), sa.ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("work_order_type", sa.String(50), nullable=False, server_default=sa.text("'production'")),
        sa.Column("status", postgresql.ENUM("scheduled", "in_progress", "completed", "cancelled", name="work_order_status_enum", create_type=False), nullable=False, server_default="scheduled"),
        sa.Column("target_quantity", sa.Integer(), nullable=False),
        sa.Column("completed_quantity", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("recommendation_id", sa.Uuid(), sa.ForeignKey("manager_recommendations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_work_orders_store_id", "work_orders", ["store_id"])

    op.create_table(
        "work_order_components",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("work_order_id", sa.Uuid(), sa.ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sku_id", sa.Uuid(), sa.ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantity_required", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_work_order_components_wo_id", "work_order_components", ["work_order_id"])

    # ------------------------------------------------------------------ #
    # 6. Stock transfers                                                   #
    # ------------------------------------------------------------------ #
    op.create_table(
        "stock_transfers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sku_id", sa.Uuid(), sa.ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("from_inventory_type", postgresql.ENUM("purchased", "material", "finished", name="inventory_type_enum", create_type=False), nullable=False),
        sa.Column("to_inventory_type", postgresql.ENUM("purchased", "material", "finished", name="inventory_type_enum", create_type=False), nullable=False),
        sa.Column("status", postgresql.ENUM("pending", "in_transit", "received", "cancelled", name="stock_transfer_status_enum", create_type=False), nullable=False, server_default="in_transit"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("recommendation_id", sa.Uuid(), sa.ForeignKey("manager_recommendations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_stock_transfers_store_id", "stock_transfers", ["store_id"])


def downgrade() -> None:
    op.drop_table("stock_transfers")
    op.drop_table("work_order_components")
    op.drop_table("work_orders")
    op.drop_table("manager_recommendations")
    op.drop_table("inventory_adjustment_logs")
    op.drop_column("inventories", "primary_supplier_id")
    op.drop_column("inventories", "sourcing_strategy")
    op.drop_column("inventories", "inventory_type")
    for t in ["stock_transfer_status_enum", "work_order_status_enum",
              "recommendation_status_enum", "recommendation_type_enum",
              "sourcing_strategy_enum", "inventory_type_enum"]:
        op.execute(sa.text(f"DROP TYPE IF EXISTS {t}"))
