from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import TimestampMixin, UUIDMixin
from app.schemas.inventory import InventoryType, SourcingStrategy


class SupplyActionSource(str, Enum):
    manual = "manual"
    recommendation = "recommendation"
    system = "system"


class SupplierBase(BaseModel):
    name: str = Field(..., max_length=255)
    contact_name: str | None = Field(None, max_length=255)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=64)
    lead_time_days: int = Field(7, ge=0, le=365)
    currency: str = Field("SGD", max_length=8)
    notes: str | None = Field(None, max_length=2000)
    is_active: bool = True


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    contact_name: str | None = Field(None, max_length=255)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=64)
    lead_time_days: int | None = Field(None, ge=0, le=365)
    currency: str | None = Field(None, max_length=8)
    notes: str | None = Field(None, max_length=2000)
    is_active: bool | None = None


class SupplierRead(SupplierBase, UUIDMixin, TimestampMixin):
    store_id: UUID
    created_by: UUID | None = None
    updated_by: UUID | None = None


class StageInventoryBase(BaseModel):
    store_id: UUID
    sku_id: UUID
    inventory_type: InventoryType
    sourcing_strategy: SourcingStrategy = SourcingStrategy.supplier_premade
    supplier_name: str | None = Field(None, max_length=255)
    quantity_on_hand: int = 0
    incoming_quantity: int = 0
    allocated_quantity: int = 0
    available_quantity: int = 0
    unit_cost: float | None = None
    last_reference_type: str | None = Field(None, max_length=64)
    last_reference_id: UUID | None = None
    source: SupplyActionSource = SupplyActionSource.manual


class StageInventoryRead(StageInventoryBase, UUIDMixin, TimestampMixin):
    sku_code: str = Field(..., max_length=64)
    description: str = Field(..., max_length=255)
    updated_by: UUID | None = None


class PurchaseOrderStatus(str, Enum):
    draft = "draft"
    ordered = "ordered"
    partially_received = "partially_received"
    received = "received"
    cancelled = "cancelled"


class PurchaseOrderLineCreate(BaseModel):
    sku_id: UUID
    quantity: int = Field(..., ge=1)
    unit_cost: float = Field(..., ge=0)
    note: str | None = Field(None, max_length=1000)


class PurchaseOrderLineRead(BaseModel):
    line_id: UUID
    sku_id: UUID
    sku_code: str = Field(..., max_length=64)
    description: str = Field(..., max_length=255)
    stage_inventory_type: InventoryType
    quantity: int
    unit_cost: float
    received_quantity: int = 0
    open_quantity: int = 0
    note: str | None = None


class PurchaseOrderCreate(BaseModel):
    supplier_id: UUID
    lines: list[PurchaseOrderLineCreate] = Field(..., min_length=1)
    ordered_at: date | None = None
    expected_delivery_date: date | None = None
    note: str | None = Field(None, max_length=2000)
    recommendation_id: UUID | None = None
    source: SupplyActionSource = SupplyActionSource.manual


class PurchaseOrderReceiveLine(BaseModel):
    line_id: UUID
    quantity_received: int = Field(..., ge=1)


class PurchaseOrderReceiveRequest(BaseModel):
    lines: list[PurchaseOrderReceiveLine] = Field(..., min_length=1)
    note: str | None = Field(None, max_length=2000)
    received_at: date | None = None


class PurchaseReceiptRead(UUIDMixin):
    purchase_order_id: UUID
    store_id: UUID
    note: str | None = None
    received_at: datetime
    received_by: UUID | None = None
    lines: list[PurchaseOrderReceiveLine]


class PurchaseOrderRead(UUIDMixin, TimestampMixin):
    store_id: UUID
    supplier_id: UUID
    supplier_name: str | None = None
    status: PurchaseOrderStatus
    lines: list[PurchaseOrderLineRead]
    total_quantity: int = 0
    total_cost: float = 0
    ordered_at: date | None = None
    expected_delivery_date: date | None = None
    last_received_at: datetime | None = None
    note: str | None = None
    source: SupplyActionSource = SupplyActionSource.manual
    recommendation_id: UUID | None = None
    created_by: UUID | None = None
    updated_by: UUID | None = None


class BOMComponentInput(BaseModel):
    sku_id: UUID
    quantity_required: int = Field(..., ge=1)
    note: str | None = Field(None, max_length=1000)


class BOMComponentRead(BOMComponentInput):
    sku_code: str = Field(..., max_length=64)
    description: str = Field(..., max_length=255)


class BOMRecipeCreate(BaseModel):
    finished_sku_id: UUID
    name: str = Field(..., max_length=255)
    yield_quantity: int = Field(1, ge=1)
    components: list[BOMComponentInput] = Field(..., min_length=1)
    notes: str | None = Field(None, max_length=2000)


class BOMRecipeRead(UUIDMixin, TimestampMixin):
    store_id: UUID
    finished_sku_id: UUID
    finished_sku_code: str = Field(..., max_length=64)
    finished_description: str = Field(..., max_length=255)
    name: str
    yield_quantity: int
    components: list[BOMComponentRead]
    notes: str | None = None
    created_by: UUID | None = None
    updated_by: UUID | None = None


class WorkOrderStatus(str, Enum):
    draft = "draft"
    scheduled = "scheduled"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


class WorkOrderType(str, Enum):
    standard = "standard"
    custom = "custom"


class WorkOrderCreate(BaseModel):
    finished_sku_id: UUID
    target_quantity: int = Field(..., ge=1)
    bom_id: UUID | None = None
    work_order_type: WorkOrderType = WorkOrderType.standard
    custom_components: list[BOMComponentInput] = Field(default_factory=list)
    due_date: date | None = None
    note: str | None = Field(None, max_length=2000)
    recommendation_id: UUID | None = None
    source: SupplyActionSource = SupplyActionSource.manual


class WorkOrderCompleteRequest(BaseModel):
    completed_quantity: int | None = Field(None, ge=1)
    note: str | None = Field(None, max_length=2000)


class ProductionEventRead(UUIDMixin):
    store_id: UUID
    work_order_id: UUID
    event_type: str = Field(..., max_length=64)
    output_quantity: int = 0
    note: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    consumed_components: list[BOMComponentInput] = Field(default_factory=list)


class WorkOrderRead(UUIDMixin, TimestampMixin):
    store_id: UUID
    finished_sku_id: UUID
    finished_sku_code: str = Field(..., max_length=64)
    finished_description: str = Field(..., max_length=255)
    work_order_type: WorkOrderType
    status: WorkOrderStatus
    target_quantity: int
    completed_quantity: int = 0
    bom_id: UUID | None = None
    components: list[BOMComponentRead] = Field(default_factory=list)
    due_date: date | None = None
    note: str | None = None
    source: SupplyActionSource = SupplyActionSource.manual
    recommendation_id: UUID | None = None
    created_by: UUID | None = None
    updated_by: UUID | None = None


class TransferStatus(str, Enum):
    draft = "draft"
    in_transit = "in_transit"
    received = "received"
    cancelled = "cancelled"


class StockTransferCreate(BaseModel):
    sku_id: UUID
    quantity: int = Field(..., ge=1)
    from_inventory_type: InventoryType
    to_inventory_type: InventoryType = InventoryType.finished
    note: str | None = Field(None, max_length=2000)
    recommendation_id: UUID | None = None
    source: SupplyActionSource = SupplyActionSource.manual


class StockTransferReceiveRequest(BaseModel):
    note: str | None = Field(None, max_length=2000)


class StockTransferRead(UUIDMixin, TimestampMixin):
    store_id: UUID
    sku_id: UUID
    sku_code: str = Field(..., max_length=64)
    description: str = Field(..., max_length=255)
    quantity: int
    from_inventory_type: InventoryType
    to_inventory_type: InventoryType
    status: TransferStatus
    note: str | None = None
    source: SupplyActionSource = SupplyActionSource.manual
    recommendation_id: UUID | None = None
    dispatched_at: datetime | None = None
    received_at: datetime | None = None
    created_by: UUID | None = None
    updated_by: UUID | None = None
    received_by: UUID | None = None


class SupplyChainSummaryRead(BaseModel):
    store_id: UUID
    supplier_count: int = 0
    open_purchase_orders: int = 0
    active_work_orders: int = 0
    in_transit_transfers: int = 0
    purchased_units: int = 0
    material_units: int = 0
    finished_units: int = 0
    open_recommendation_linked_orders: int = 0
