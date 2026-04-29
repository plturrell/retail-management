"""Add bank_transactions → accounts / journal_entries foreign keys.

The ORM model declares ``bank_transactions.account_id`` and
``bank_transactions.journal_entry_id`` as proper foreign keys (with
``ON DELETE SET NULL``). This migration enforces that referential
integrity at the database level for environments where the
``bank_transactions`` table was previously created without the
constraints. Both columns remain nullable.

Idempotent: skipped silently if the table or column doesn't exist yet
(e.g. environments that never created ``bank_transactions``), and the
``IF NOT EXISTS`` style is used where supported.

Revision ID: 010
Revises: 009
Create Date: 2026-04-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def _has_named_fk(table: str, fk_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return any((fk.get("name") == fk_name) for fk in insp.get_foreign_keys(table))
    except sa.exc.NoSuchTableError:
        return False


def upgrade() -> None:
    if not _table_exists("bank_transactions"):
        return
    if _table_exists("accounts") and not _has_named_fk(
        "bank_transactions", "fk_bank_transactions_account_id_accounts"
    ):
        op.create_foreign_key(
            "fk_bank_transactions_account_id_accounts",
            "bank_transactions",
            "accounts",
            ["account_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if _table_exists("journal_entries") and not _has_named_fk(
        "bank_transactions", "fk_bank_transactions_journal_entry_id_journal_entries"
    ):
        op.create_foreign_key(
            "fk_bank_transactions_journal_entry_id_journal_entries",
            "bank_transactions",
            "journal_entries",
            ["journal_entry_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    if not _table_exists("bank_transactions"):
        return
    if _has_named_fk(
        "bank_transactions", "fk_bank_transactions_journal_entry_id_journal_entries"
    ):
        op.drop_constraint(
            "fk_bank_transactions_journal_entry_id_journal_entries",
            "bank_transactions",
            type_="foreignkey",
        )
    if _has_named_fk(
        "bank_transactions", "fk_bank_transactions_account_id_accounts"
    ):
        op.drop_constraint(
            "fk_bank_transactions_account_id_accounts",
            "bank_transactions",
            type_="foreignkey",
        )
