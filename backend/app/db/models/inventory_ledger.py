"""Inventory ledger ORM models.

`StockMovement` is an append-only ledger of every inventory delta — manual
adjustments, CSV imports, purchase-order receipts, work-order completions,
transfers, etc. Each row records the *change* (`delta_qty`) and a snapshot of
the resulting on-hand quantity for the affected (store, sku) at the time of
write, so analytical queries (running totals, cohort queries) don't need to
recompute from the beginning of time.

This table dual-writes alongside the Firestore `inventory_adjustments` and
stage-inventory writes during the migration; reads are TBD.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum as SAEnum,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class StockMovementSource(str, enum.Enum):
    """Origin of a stock movement. Mirrors the Firestore `source` strings.

    Values are stored as strings in the DB so future variants can be added
    without an ALTER TABLE — TiDB doesn't enforce ENUM strictly anyway.
    """

    manual = "manual"
    csv_import = "csv_import"
    nec_pos = "nec_pos"
    purchase_order = "purchase_order"
    work_order = "work_order"
    transfer = "transfer"
    system = "system"
    recommendation = "recommendation"


class StockMovement(Base):
    """A single ledger entry. Append-only — never updated in place."""

    __tablename__ = "stock_movements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    store_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    sku_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    inventory_type: Mapped[str] = mapped_column(String(32), nullable=False, default="finished")

    delta_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_qty: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    source: Mapped[str] = mapped_column(
        SAEnum(StockMovementSource, native_enum=False, length=32, validate_strings=False),
        nullable=False,
        default=StockMovementSource.manual.value,
    )
    reference_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reference_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    actor_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)

    # Use server time for ordering so out-of-order client clocks don't break
    # ledger semantics. We also store an explicit `event_time` in case the
    # caller wants to back-date (e.g. CSV imports of historical data).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Useful composite indexes for the most common analytical queries.
    __table_args__ = (
        Index("ix_stock_movements_store_sku_event", "store_id", "sku_id", "event_time"),
        Index("ix_stock_movements_store_event", "store_id", "event_time"),
    )

    def __repr__(self) -> str:  # pragma: no cover — debug aid only
        return (
            f"<StockMovement id={self.id} store={self.store_id} sku={self.sku_id} "
            f"delta={self.delta_qty} src={self.source}>"
        )
