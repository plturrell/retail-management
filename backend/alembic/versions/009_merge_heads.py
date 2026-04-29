"""Consolidate the alembic head graph.

Resolves three parallel heads that emerged during the master-data /
salesperson / stock-movements work:

  * ``008``                   — salesperson_attribution (chain through ``007``)
  * ``007b_master_data``      — master data structures (parallel to ``007``)
  * ``0001``                  — orphan stock_movements baseline (no parent)

After this revision lands, the graph has a single head (``009``) and
forward migrations such as the banking-FK addition can stack cleanly on
top.

Revision ID: 009
Revises: 008, 007b_master_data, 0001
Create Date: 2026-04-29
"""
from typing import Sequence, Union


revision: str = "009"
down_revision: Union[str, Sequence[str], None] = ("008", "007b_master_data", "0001")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge migration — no schema changes."""
    pass


def downgrade() -> None:
    """Merge migration — no schema changes."""
    pass
