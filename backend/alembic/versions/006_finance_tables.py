"""Add finance tables: accounts, journal_entries, journal_lines

Revision ID: 006
Revises: 005
Create Date: 2026-04-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(20), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "account_type",
            sa.Enum("asset", "liability", "equity", "revenue", "expense", name="account_type_enum"),
            nullable=False,
        ),
        sa.Column("parent_id", sa.Uuid(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("entry_number", sa.String(30), unique=True, nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("source_ref", sa.String(255), nullable=True),
        sa.Column("is_posted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("posted_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "journal_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "journal_entry_id",
            sa.Uuid(),
            sa.ForeignKey("journal_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("debit", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("credit", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("journal_lines")
    op.drop_table("journal_entries")
    op.drop_table("accounts")
    op.execute("DROP TYPE IF EXISTS account_type_enum")
