"""Add master data structures: customers, suppliers, purchases, marketing, staff HR

Revision ID: 007b_master_data
Revises: 006
Create Date: 2026-04-13

Note: originally numbered ``007`` but collided with ``007_commission_tables``.
Renamed to ``007b_master_data`` to give Alembic a unique revision id while
preserving the migration's downgrade target. Resolved together with
``007_commission_tables`` and the orphan ``0001_create_stock_movements`` in
the merge migration ``009_merge_heads``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "007b_master_data"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. Alter stores table — add new master location fields              #
    # ------------------------------------------------------------------ #
    op.execute(
        "CREATE TYPE store_type_enum AS ENUM ('flagship', 'outlet', 'pop_up', 'warehouse', 'online')"
    )
    op.add_column("stores", sa.Column("store_code", sa.String(20), nullable=True))
    op.add_column(
        "stores",
        sa.Column(
            "store_type",
            sa.Enum("flagship", "outlet", "pop_up", "warehouse", "online", name="store_type_enum"),
            nullable=True,
        ),
    )
    op.add_column("stores", sa.Column("city", sa.String(100), nullable=True))
    op.add_column("stores", sa.Column("country", sa.String(100), nullable=True))
    op.add_column("stores", sa.Column("postal_code", sa.String(20), nullable=True))
    op.add_column("stores", sa.Column("phone", sa.String(50), nullable=True))
    op.add_column("stores", sa.Column("email", sa.String(255), nullable=True))
    op.add_column(
        "stores",
        sa.Column("currency", sa.String(3), nullable=False, server_default=sa.text("'SGD'")),
    )
    # Back-fill store_code from name, then enforce not null + unique
    op.execute("UPDATE stores SET store_code = UPPER(REPLACE(SUBSTRING(name, 1, 10), ' ', '')) WHERE store_code IS NULL")
    op.execute("UPDATE stores SET store_type = 'outlet' WHERE store_type IS NULL")
    op.execute("UPDATE stores SET city = 'Singapore' WHERE city IS NULL")
    op.execute("UPDATE stores SET country = 'Singapore' WHERE country IS NULL")
    op.alter_column("stores", "store_code", nullable=False)
    op.alter_column("stores", "store_type", nullable=False)
    op.create_unique_constraint("uq_store_code", "stores", ["store_code"])
    op.create_index("ix_stores_store_code", "stores", ["store_code"])

    # ------------------------------------------------------------------ #
    # 2. Staff HR — departments, job_positions                            #
    # ------------------------------------------------------------------ #
    op.create_table(
        "departments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(20), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.execute(
        "CREATE TYPE position_level_enum AS ENUM ('entry', 'junior', 'senior', 'lead', 'manager', 'director')"
    )
    op.create_table(
        "job_positions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(20), unique=True, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("department_id", sa.Uuid(), sa.ForeignKey("departments.id"), nullable=False),
        sa.Column(
            "level",
            sa.Enum("entry", "junior", "senior", "lead", "manager", "director", name="position_level_enum"),
            nullable=False,
            server_default=sa.text("'entry'"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Leave management
    op.create_table(
        "leave_types",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(20), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_paid", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("days_per_year", sa.Numeric(5, 1), nullable=False),
        sa.Column("carry_over_days", sa.Numeric(5, 1), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.execute(
        "CREATE TYPE leave_status_enum AS ENUM ('pending', 'approved', 'rejected', 'cancelled')"
    )
    op.create_table(
        "leave_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("leave_type_id", sa.Uuid(), sa.ForeignKey("leave_types.id"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("days_requested", sa.Numeric(5, 1), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", "cancelled", name="leave_status_enum"),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "leave_balances",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("leave_type_id", sa.Uuid(), sa.ForeignKey("leave_types.id"), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("entitled_days", sa.Numeric(5, 1), nullable=False),
        sa.Column("used_days", sa.Numeric(5, 1), nullable=False, server_default=sa.text("0")),
        sa.Column("pending_days", sa.Numeric(5, 1), nullable=False, server_default=sa.text("0")),
        sa.Column("carried_over_days", sa.Numeric(5, 1), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "leave_type_id", "year", name="uq_leave_balance"),
    )

    # Alter employee_profiles to add employment type, department, position
    op.execute(
        "CREATE TYPE employment_type_enum AS ENUM ('full_time', 'part_time', 'contract', 'intern')"
    )
    op.add_column(
        "employee_profiles",
        sa.Column(
            "employment_type",
            sa.Enum("full_time", "part_time", "contract", "intern", name="employment_type_enum"),
            nullable=True,
        ),
    )
    op.add_column(
        "employee_profiles",
        sa.Column("department_id", sa.Uuid(), sa.ForeignKey("departments.id"), nullable=True),
    )
    op.add_column(
        "employee_profiles",
        sa.Column("job_position_id", sa.Uuid(), sa.ForeignKey("job_positions.id"), nullable=True),
    )
    op.execute("UPDATE employee_profiles SET employment_type = 'full_time' WHERE employment_type IS NULL")
    op.alter_column("employee_profiles", "employment_type", nullable=False)

    # ------------------------------------------------------------------ #
    # 3. Customer master                                                  #
    # ------------------------------------------------------------------ #
    op.execute(
        "CREATE TYPE customer_gender_enum AS ENUM ('male', 'female', 'other', 'prefer_not_to_say')"
    )
    op.execute(
        "CREATE TYPE loyalty_tier_enum AS ENUM ('bronze', 'silver', 'gold', 'platinum')"
    )
    op.execute(
        "CREATE TYPE loyalty_txn_type_enum AS ENUM ('earn', 'redeem', 'adjust', 'expire')"
    )
    op.execute(
        "CREATE TYPE address_type_enum AS ENUM ('home', 'work', 'other')"
    )

    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("customer_code", sa.String(30), unique=True, nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), unique=True, nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column(
            "gender",
            sa.Enum("male", "female", "other", "prefer_not_to_say", name="customer_gender_enum"),
            nullable=True,
        ),
        sa.Column(
            "registered_store_id",
            sa.Uuid(),
            sa.ForeignKey("stores.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_customers_customer_code", "customers", ["customer_code"])
    op.create_index("ix_customers_email", "customers", ["email"])

    op.create_table(
        "customer_addresses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "customer_id",
            sa.Uuid(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "address_type",
            sa.Enum("home", "work", "other", name="address_type_enum"),
            nullable=False,
            server_default=sa.text("'home'"),
        ),
        sa.Column("address_line1", sa.String(255), nullable=False),
        sa.Column("address_line2", sa.String(255), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("country", sa.String(100), nullable=False, server_default=sa.text("'Singapore'")),
        sa.Column("postal_code", sa.String(20), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "loyalty_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "customer_id",
            sa.Uuid(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tier",
            sa.Enum("bronze", "silver", "gold", "platinum", name="loyalty_tier_enum"),
            nullable=False,
            server_default=sa.text("'bronze'"),
        ),
        sa.Column("points_balance", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("lifetime_points", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("joined_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("customer_id", name="uq_loyalty_customer"),
    )

    op.create_table(
        "loyalty_transactions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "loyalty_account_id",
            sa.Uuid(),
            sa.ForeignKey("loyalty_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "transaction_type",
            sa.Enum("earn", "redeem", "adjust", "expire", name="loyalty_txn_type_enum"),
            nullable=False,
        ),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("reference_type", sa.String(50), nullable=True),
        sa.Column("reference_id", sa.String(100), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Add customer_id to orders
    op.add_column(
        "orders",
        sa.Column(
            "customer_id",
            sa.Uuid(),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # ------------------------------------------------------------------ #
    # 4. Suppliers                                                        #
    # ------------------------------------------------------------------ #
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("supplier_code", sa.String(30), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("contact_person", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("country", sa.String(100), nullable=False, server_default=sa.text("'Singapore'")),
        sa.Column("currency", sa.String(3), nullable=False, server_default=sa.text("'SGD'")),
        sa.Column("payment_terms_days", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column("gst_registered", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("gst_number", sa.String(50), nullable=True),
        sa.Column("bank_account", sa.String(50), nullable=True),
        sa.Column("bank_name", sa.String(100), nullable=True),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_suppliers_supplier_code", "suppliers", ["supplier_code"])

    op.create_table(
        "supplier_products",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("supplier_id", sa.Uuid(), sa.ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sku_id", sa.Uuid(), sa.ForeignKey("skus.id", ondelete="CASCADE"), nullable=False),
        sa.Column("supplier_sku_code", sa.String(100), nullable=True),
        sa.Column("supplier_unit_cost", sa.Numeric(20, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default=sa.text("'SGD'")),
        sa.Column("min_order_qty", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("lead_time_days", sa.Integer(), nullable=False, server_default=sa.text("7")),
        sa.Column("is_preferred", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------ #
    # 5. Purchasing & Expenses                                            #
    # ------------------------------------------------------------------ #
    op.execute(
        "CREATE TYPE po_status_enum AS ENUM ('draft', 'submitted', 'confirmed', 'partially_received', 'fully_received', 'cancelled')"
    )
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("po_number", sa.String(50), unique=True, nullable=False),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("expected_delivery_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("draft", "submitted", "confirmed", "partially_received", "fully_received", "cancelled", name="po_status_enum"),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("subtotal", sa.Numeric(20, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("tax_total", sa.Numeric(20, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("grand_total", sa.Numeric(20, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("currency", sa.String(3), nullable=False, server_default=sa.text("'SGD'")),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_purchase_orders_po_number", "purchase_orders", ["po_number"])

    op.create_table(
        "purchase_order_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("purchase_order_id", sa.Uuid(), sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sku_id", sa.Uuid(), sa.ForeignKey("skus.id"), nullable=False),
        sa.Column("qty_ordered", sa.Integer(), nullable=False),
        sa.Column("qty_received", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("unit_cost", sa.Numeric(20, 2), nullable=False),
        sa.Column("tax_code", sa.String(1), nullable=False, server_default=sa.text("'G'")),
        sa.Column("line_total", sa.Numeric(20, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.execute(
        "CREATE TYPE grn_status_enum AS ENUM ('pending', 'partial', 'complete')"
    )
    op.execute(
        "CREATE TYPE goods_condition_enum AS ENUM ('good', 'damaged', 'rejected')"
    )
    op.create_table(
        "goods_receipts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("grn_number", sa.String(50), unique=True, nullable=False),
        sa.Column("purchase_order_id", sa.Uuid(), sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("received_date", sa.Date(), nullable=False),
        sa.Column("received_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "partial", "complete", name="grn_status_enum"),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_goods_receipts_grn_number", "goods_receipts", ["grn_number"])

    op.create_table(
        "goods_receipt_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("goods_receipt_id", sa.Uuid(), sa.ForeignKey("goods_receipts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("po_item_id", sa.Uuid(), sa.ForeignKey("purchase_order_items.id"), nullable=False),
        sa.Column("sku_id", sa.Uuid(), sa.ForeignKey("skus.id"), nullable=False),
        sa.Column("qty_received", sa.Integer(), nullable=False),
        sa.Column(
            "condition",
            sa.Enum("good", "damaged", "rejected", name="goods_condition_enum"),
            nullable=False,
            server_default=sa.text("'good'"),
        ),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "expense_categories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(20), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.execute(
        "CREATE TYPE expense_status_enum AS ENUM ('pending', 'approved', 'paid', 'rejected')"
    )
    op.create_table(
        "expenses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("expense_number", sa.String(50), unique=True, nullable=False),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("expense_categories.id"), nullable=False),
        sa.Column("vendor_name", sa.String(255), nullable=True),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("amount_excl_tax", sa.Numeric(20, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(20, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("amount_incl_tax", sa.Numeric(20, 2), nullable=False),
        sa.Column("payment_method", sa.String(50), nullable=True),
        sa.Column("payment_ref", sa.String(255), nullable=True),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("receipt_url", sa.String(1000), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "paid", "rejected", name="expense_status_enum"),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("submitted_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_expenses_expense_number", "expenses", ["expense_number"])

    # ------------------------------------------------------------------ #
    # 6. Marketing                                                        #
    # ------------------------------------------------------------------ #
    op.execute(
        "CREATE TYPE campaign_type_enum AS ENUM ('discount', 'points_multiplier', 'free_gift', 'bundle')"
    )
    op.execute(
        "CREATE TYPE campaign_status_enum AS ENUM ('draft', 'active', 'paused', 'ended')"
    )
    op.execute(
        "CREATE TYPE campaign_disc_method_enum AS ENUM ('fixed', 'percentage')"
    )
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("campaign_code", sa.String(30), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column(
            "campaign_type",
            sa.Enum("discount", "points_multiplier", "free_gift", "bundle", name="campaign_type_enum"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("draft", "active", "paused", "ended", name="campaign_status_enum"),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="SET NULL"), nullable=True),
        sa.Column("budget", sa.Numeric(20, 2), nullable=True),
        sa.Column(
            "disc_method",
            sa.Enum("fixed", "percentage", name="campaign_disc_method_enum"),
            nullable=True,
        ),
        sa.Column("disc_value", sa.Numeric(11, 2), nullable=True),
        sa.Column("points_multiplier", sa.Numeric(5, 2), nullable=True),
        sa.Column("min_purchase_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("uses_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_campaigns_campaign_code", "campaigns", ["campaign_code"])

    op.create_table(
        "campaign_skus",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sku_id", sa.Uuid(), sa.ForeignKey("skus.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("campaign_id", "sku_id", name="uq_campaign_sku"),
    )

    op.create_table(
        "campaign_categories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("categories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("campaign_id", "category_id", name="uq_campaign_category"),
    )

    op.execute(
        "CREATE TYPE voucher_type_enum AS ENUM ('gift_card', 'discount_voucher', 'loyalty_voucher')"
    )
    op.execute(
        "CREATE TYPE voucher_status_enum AS ENUM ('active', 'redeemed', 'expired', 'voided')"
    )
    op.create_table(
        "vouchers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("voucher_code", sa.String(50), unique=True, nullable=False),
        sa.Column(
            "voucher_type",
            sa.Enum("gift_card", "discount_voucher", "loyalty_voucher", name="voucher_type_enum"),
            nullable=False,
        ),
        sa.Column("face_value", sa.Numeric(20, 2), nullable=False),
        sa.Column("balance", sa.Numeric(20, 2), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "redeemed", "expired", "voided", name="voucher_status_enum"),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("issued_to_customer_id", sa.Uuid(), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("issued_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(), nullable=True),
        sa.Column("redeemed_order_id", sa.Uuid(), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_vouchers_voucher_code", "vouchers", ["voucher_code"])

    op.create_table(
        "customer_segments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("criteria", postgresql.JSONB(), nullable=True),
        sa.Column("is_dynamic", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "customer_segment_members",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("segment_id", sa.Uuid(), sa.ForeignKey("customer_segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("segment_id", "customer_id", name="uq_segment_customer"),
    )


def downgrade() -> None:
    # Marketing
    op.drop_table("customer_segment_members")
    op.drop_table("customer_segments")
    op.drop_index("ix_vouchers_voucher_code", table_name="vouchers")
    op.drop_table("vouchers")
    op.drop_table("campaign_categories")
    op.drop_table("campaign_skus")
    op.drop_index("ix_campaigns_campaign_code", table_name="campaigns")
    op.drop_table("campaigns")
    op.execute("DROP TYPE IF EXISTS voucher_status_enum")
    op.execute("DROP TYPE IF EXISTS voucher_type_enum")
    op.execute("DROP TYPE IF EXISTS campaign_disc_method_enum")
    op.execute("DROP TYPE IF EXISTS campaign_status_enum")
    op.execute("DROP TYPE IF EXISTS campaign_type_enum")

    # Purchasing & Expenses
    op.drop_index("ix_expenses_expense_number", table_name="expenses")
    op.drop_table("expenses")
    op.drop_table("expense_categories")
    op.drop_table("goods_receipt_items")
    op.drop_index("ix_goods_receipts_grn_number", table_name="goods_receipts")
    op.drop_table("goods_receipts")
    op.drop_table("purchase_order_items")
    op.drop_index("ix_purchase_orders_po_number", table_name="purchase_orders")
    op.drop_table("purchase_orders")
    op.execute("DROP TYPE IF EXISTS expense_status_enum")
    op.execute("DROP TYPE IF EXISTS goods_condition_enum")
    op.execute("DROP TYPE IF EXISTS grn_status_enum")
    op.execute("DROP TYPE IF EXISTS po_status_enum")

    # Suppliers
    op.drop_table("supplier_products")
    op.drop_index("ix_suppliers_supplier_code", table_name="suppliers")
    op.drop_table("suppliers")

    # Customer
    op.drop_column("orders", "customer_id")
    op.drop_table("loyalty_transactions")
    op.drop_table("loyalty_accounts")
    op.drop_table("customer_addresses")
    op.drop_index("ix_customers_email", table_name="customers")
    op.drop_index("ix_customers_customer_code", table_name="customers")
    op.drop_table("customers")
    op.execute("DROP TYPE IF EXISTS address_type_enum")
    op.execute("DROP TYPE IF EXISTS loyalty_txn_type_enum")
    op.execute("DROP TYPE IF EXISTS loyalty_tier_enum")
    op.execute("DROP TYPE IF EXISTS customer_gender_enum")

    # Staff HR
    op.drop_column("employee_profiles", "job_position_id")
    op.drop_column("employee_profiles", "department_id")
    op.drop_column("employee_profiles", "employment_type")
    op.execute("DROP TYPE IF EXISTS employment_type_enum")
    op.drop_table("leave_balances")
    op.drop_table("leave_requests")
    op.drop_table("leave_types")
    op.execute("DROP TYPE IF EXISTS leave_status_enum")
    op.drop_table("job_positions")
    op.execute("DROP TYPE IF EXISTS position_level_enum")
    op.drop_table("departments")

    # Store fields
    op.drop_constraint("uq_store_code", "stores", type_="unique")
    op.drop_index("ix_stores_store_code", table_name="stores")
    op.drop_column("stores", "currency")
    op.drop_column("stores", "email")
    op.drop_column("stores", "phone")
    op.drop_column("stores", "postal_code")
    op.drop_column("stores", "country")
    op.drop_column("stores", "city")
    op.drop_column("stores", "store_type")
    op.drop_column("stores", "store_code")
    op.execute("DROP TYPE IF EXISTS store_type_enum")
