"""Models for Inventory Copilot, Supply Chain, and Work Orders."""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Date, Float, ForeignKey,
    Integer, Numeric, String, Text, UniqueConstraint,
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._mixins import uuid_pk, created_at_col, updated_at_col


# ------------------------------------------------------------------ #
# Shared enums                                                         #
# ------------------------------------------------------------------ #

class InventoryType(str, enum.Enum):
    purchased = "purchased"
    material = "material"
    finished = "finished"


class SourcingStrategy(str, enum.Enum):
    supplier_premade = "supplier_premade"
    manufactured_standard = "manufactured_standard"
    manufactured_custom = "manufactured_custom"


# ------------------------------------------------------------------ #
# Inventory adjustment log                                             #
# ------------------------------------------------------------------ #

class InventoryAdjustmentLog(Base):
    __tablename__ = "inventory_adjustment_logs"

    id: Mapped[uuid_pk]
    inventory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id", ondelete="CASCADE"), nullable=False
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False, default="manual")
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[created_at_col]


# ------------------------------------------------------------------ #
# Manager recommendations (Copilot)                                    #
# ------------------------------------------------------------------ #

class RecommendationType(str, enum.Enum):
    reorder = "reorder"
    price_change = "price_change"
    stock_anomaly = "stock_anomaly"


class RecommendationStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    applied = "applied"
    expired = "expired"
    queued = "queued"
    unavailable = "unavailable"


class ManagerRecommendation(Base):
    __tablename__ = "manager_recommendations"

    id: Mapped[uuid_pk]
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sku_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id", ondelete="SET NULL"), nullable=True
    )
    inventory_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventories.id", ondelete="SET NULL"), nullable=True
    )
    inventory_type: Mapped[str] = mapped_column(
        SQLEnum(InventoryType, name="inventory_type_enum"), nullable=False, default="purchased"
    )
    sourcing_strategy: Mapped[str] = mapped_column(
        SQLEnum(SourcingStrategy, name="sourcing_strategy_enum"), nullable=False, default="supplier_premade"
    )
    supplier_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    rec_type: Mapped[str] = mapped_column(
        SQLEnum(RecommendationType, name="recommendation_type_enum"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        SQLEnum(RecommendationStatus, name="recommendation_status_enum"),
        nullable=False, default="pending"
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    supporting_metrics: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False, default="rules_engine")
    expected_impact: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    current_price: Mapped[Optional[float]] = mapped_column(Numeric(20, 2), nullable=True)
    suggested_price: Mapped[Optional[float]] = mapped_column(Numeric(20, 2), nullable=True)
    suggested_order_qty: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    workflow_action: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    analysis_status: Mapped[str] = mapped_column(String(50), nullable=False, default="complete")
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]


# ------------------------------------------------------------------ #
# Work orders                                                          #
# ------------------------------------------------------------------ #

class WorkOrderStatus(str, enum.Enum):
    scheduled = "scheduled"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[uuid_pk]
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    finished_sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False
    )
    work_order_type: Mapped[str] = mapped_column(String(50), nullable=False, default="production")
    status: Mapped[str] = mapped_column(
        SQLEnum(WorkOrderStatus, name="work_order_status_enum"), nullable=False, default="scheduled"
    )
    target_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recommendation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("manager_recommendations.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    components: Mapped[list["WorkOrderComponent"]] = relationship(
        "WorkOrderComponent", back_populates="work_order", lazy="selectin"
    )


class WorkOrderComponent(Base):
    __tablename__ = "work_order_components"

    id: Mapped[uuid_pk]
    work_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_required: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[created_at_col]

    work_order: Mapped["WorkOrder"] = relationship("WorkOrder", back_populates="components")


# ------------------------------------------------------------------ #
# Stock transfers (stage-to-stage within a store)                      #
# ------------------------------------------------------------------ #

class StockTransferStatus(str, enum.Enum):
    pending = "pending"
    in_transit = "in_transit"
    received = "received"
    cancelled = "cancelled"


class StockTransfer(Base):
    __tablename__ = "stock_transfers"

    id: Mapped[uuid_pk]
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    from_inventory_type: Mapped[str] = mapped_column(
        SQLEnum(InventoryType, name="inventory_type_enum"), nullable=False
    )
    to_inventory_type: Mapped[str] = mapped_column(
        SQLEnum(InventoryType, name="inventory_type_enum"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        SQLEnum(StockTransferStatus, name="stock_transfer_status_enum"),
        nullable=False, default="in_transit"
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recommendation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("manager_recommendations.id", ondelete="SET NULL"), nullable=True
    )
    dispatched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]
