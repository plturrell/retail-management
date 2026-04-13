"""Add commission tables and fields

Revision ID: 007
Revises: 006
Create Date: 2026-04-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add commission_rate to employee_profiles
    op.add_column(
        "employee_profiles",
        sa.Column("commission_rate", sa.Numeric(5, 2), nullable=True),
    )

    # Add commission fields to payslips
    op.add_column(
        "payslips",
        sa.Column(
            "commission_sales",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "payslips",
        sa.Column(
            "commission_amount",
            sa.Numeric(10, 2),
            nullable=False,
            server_default="0",
        ),
    )

    # Create commission_rules table
    op.create_table(
        "commission_rules",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
        ),
        sa.Column(
            "store_id",
            UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("tiers", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Create commission_entries table
    op.create_table(
        "commission_entries",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
        ),
        sa.Column(
            "payslip_id",
            UUID(as_uuid=True),
            sa.ForeignKey("payslips.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "commission_rule_id",
            UUID(as_uuid=True),
            sa.ForeignKey("commission_rules.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sales_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("commission_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("rule_name", sa.String(200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("commission_entries")
    op.drop_table("commission_rules")
    op.drop_column("payslips", "commission_amount")
    op.drop_column("payslips", "commission_sales")
    op.drop_column("employee_profiles", "commission_rate")
