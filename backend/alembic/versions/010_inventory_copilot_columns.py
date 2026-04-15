"""Add copilot columns to inventories table.

Revision ID: 010
Revises: 009
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum types if they don't exist
    op.execute("DO $$ BEGIN CREATE TYPE inventory_type_enum AS ENUM ('purchased', 'material', 'finished'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE sourcing_strategy_enum AS ENUM ('supplier_premade', 'manufactured_standard', 'manufactured_custom'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")

    op.add_column(
        "inventories",
        sa.Column(
            "inventory_type",
            sa.Enum("purchased", "material", "finished", name="inventory_type_enum", create_type=False),
            nullable=False,
            server_default="purchased",
        ),
    )
    op.add_column(
        "inventories",
        sa.Column(
            "sourcing_strategy",
            sa.Enum("supplier_premade", "manufactured_standard", "manufactured_custom", name="sourcing_strategy_enum", create_type=False),
            nullable=False,
            server_default="supplier_premade",
        ),
    )
    op.add_column(
        "inventories",
        sa.Column(
            "primary_supplier_id",
            UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("inventories", "primary_supplier_id")
    op.drop_column("inventories", "sourcing_strategy")
    op.drop_column("inventories", "inventory_type")
