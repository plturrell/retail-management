from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import TimestampMixin, UUIDMixin
from app.schemas.inventory import InventoryType, SourcingStrategy


class AuditSource(str, Enum):
    manual = "manual"
    multica_recommendation = "multica_recommendation"
    system = "system"


class RecommendationType(str, Enum):
    reorder = "reorder"
    price_change = "price_change"
    stock_anomaly = "stock_anomaly"


class RecommendationStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    applied = "applied"
    expired = "expired"
    queued = "queued"
    unavailable = "unavailable"


class RecommendationBase(BaseModel):
    store_id: UUID
    sku_id: UUID | None = None
    inventory_id: UUID | None = None
    inventory_type: InventoryType = InventoryType.finished
    sourcing_strategy: SourcingStrategy = SourcingStrategy.supplier_premade
    supplier_name: str | None = Field(None, max_length=255)
    type: RecommendationType
    status: RecommendationStatus
    title: str = Field(..., max_length=160)
    rationale: str = Field(..., max_length=4000)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    supporting_metrics: dict[str, Any] = Field(default_factory=dict)
    source: AuditSource = AuditSource.multica_recommendation
    expected_impact: str | None = Field(None, max_length=1000)
    current_price: float | None = None
    suggested_price: float | None = None
    suggested_order_qty: int | None = None
    workflow_action: str | None = Field(None, max_length=64)
    analysis_status: str = "completed"
    generated_at: datetime
    decided_at: datetime | None = None
    decided_by: UUID | None = None
    applied_at: datetime | None = None
    applied_by: UUID | None = None
    note: str | None = Field(None, max_length=1000)


class RecommendationRead(RecommendationBase, UUIDMixin, TimestampMixin):
    dedupe_key: str | None = None


class RecommendationPublicRead(BaseModel):
    id: UUID
    store_id: UUID
    sku_id: UUID | None = None
    inventory_id: UUID | None = None
    inventory_type: InventoryType = InventoryType.finished
    sourcing_strategy: SourcingStrategy = SourcingStrategy.supplier_premade
    supplier_name: str | None = None
    type: RecommendationType
    status: RecommendationStatus
    title: str
    rationale: str
    confidence: float
    supporting_metrics: dict[str, Any] = Field(default_factory=dict)
    source: AuditSource = AuditSource.multica_recommendation
    expected_impact: str | None = None
    current_price: float | None = None
    suggested_price: float | None = None
    suggested_order_qty: int | None = None
    workflow_action: str | None = None
    analysis_status: str = "completed"
    generated_at: datetime
    decided_at: datetime | None = None
    applied_at: datetime | None = None
    note: str | None = None


class RecommendationDecisionRequest(BaseModel):
    note: str | None = Field(None, max_length=1000)


class RecommendationApplyRequest(BaseModel):
    note: str | None = Field(None, max_length=1000)
    effective_date: date | None = None


class RecommendationTriggerRequest(BaseModel):
    force_refresh: bool = False
    lookback_days: int = Field(30, ge=7, le=120)
    low_stock_threshold: int = Field(5, ge=0, le=500)


class RecommendationTriggerResponse(BaseModel):
    analysis_status: str
    multica_status: str
    recommendations_created: int
    recommendations_reused: int
    recommendations: list[RecommendationPublicRead]


class RecommendationOutcomeRead(BaseModel):
    recommendation_id: UUID
    sku_id: UUID | None = None
    title: str
    type: RecommendationType
    status: RecommendationStatus
    updated_at: datetime | None = None


class ManagerSummaryRead(BaseModel):
    store_id: UUID
    analysis_status: str
    last_generated_at: datetime | None = None
    low_stock_count: int = 0
    anomaly_count: int = 0
    pending_price_recommendations: int = 0
    pending_reorder_recommendations: int = 0
    pending_stock_anomalies: int = 0
    open_purchase_orders: int = 0
    active_work_orders: int = 0
    in_transit_transfers: int = 0
    purchased_units: int = 0
    material_units: int = 0
    finished_units: int = 0
    recent_outcomes: list[RecommendationOutcomeRead] = Field(default_factory=list)


class InventoryInsightRead(BaseModel):
    inventory_id: UUID | None = None
    sku_id: UUID
    store_id: UUID
    sku_code: str
    description: str
    long_description: str | None = None
    inventory_type: InventoryType = InventoryType.finished
    sourcing_strategy: SourcingStrategy = SourcingStrategy.supplier_premade
    supplier_name: str | None = None
    cost_price: float | None = None
    current_price: float | None = None
    current_price_valid_until: date | None = None
    purchased_qty: int = 0
    purchased_incoming_qty: int = 0
    material_qty: int = 0
    material_incoming_qty: int = 0
    material_allocated_qty: int = 0
    finished_qty: int = 0
    finished_allocated_qty: int = 0
    in_transit_qty: int = 0
    active_work_order_count: int = 0
    qty_on_hand: int = 0
    reorder_level: int = 0
    reorder_qty: int = 0
    low_stock: bool = False
    anomaly_flag: bool = False
    anomaly_reason: str | None = None
    recent_sales_qty: int = 0
    recent_sales_revenue: float = 0
    avg_daily_sales: float = 0
    days_of_cover: float | None = None
    pending_recommendation_count: int = 0
    pending_price_recommendation_count: int = 0
    last_updated: datetime | None = None


class InventoryAdjustmentHistoryRead(UUIDMixin):
    inventory_id: UUID
    sku_id: UUID
    store_id: UUID
    quantity_delta: int
    resulting_qty: int
    reason: str
    source: AuditSource = AuditSource.manual
    created_by: UUID | None = None
    recommendation_id: UUID | None = None
    note: str | None = None
    created_at: datetime
