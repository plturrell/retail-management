from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import TimestampMixin, UUIDMixin


class OrderItemBase(BaseModel):
    sku_id: UUID
    qty: int = Field(..., gt=0)
    unit_price: float
    discount: float = 0
    line_total: float


class OrderItemCreate(OrderItemBase):
    pass


class OrderItemRead(OrderItemBase, UUIDMixin):
    order_id: UUID
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class OrderBase(BaseModel):
    store_id: UUID
    staff_id: UUID | None = None
    salesperson_id: UUID | None = None
    order_date: datetime
    subtotal: float
    discount_total: float = 0
    tax_total: float = 0
    grand_total: float
    payment_method: str = Field(..., max_length=50)
    payment_ref: str | None = Field(None, max_length=255)
    status: str = "open"
    source: str = "manual"


class OrderCreate(BaseModel):
    store_id: UUID
    staff_id: UUID | None = None
    order_date: datetime | None = None
    payment_method: str = Field(..., max_length=50)
    payment_ref: str | None = Field(None, max_length=255)
    source: str = "manual"
    items: list[OrderItemCreate]


class OrderUpdate(BaseModel):
    status: str | None = None
    payment_method: str | None = Field(None, max_length=50)
    payment_ref: str | None = Field(None, max_length=255)


class OrderRead(OrderBase, UUIDMixin, TimestampMixin):
    order_number: str
    items: list[OrderItemRead] = []


# ─── Salesperson Alias Schemas ─────────────────────────────────────


class SalespersonAliasCreate(BaseModel):
    alias_name: str = Field(..., max_length=255)
    user_id: UUID


class SalespersonAliasRead(BaseModel):
    id: UUID
    alias_name: str
    user_id: UUID
    store_id: UUID
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ─── By-Staff Sales Schemas ────────────────────────────────────────


class StaffSalesSummary(BaseModel):
    salesperson_id: UUID | None = None
    salesperson_name: str | None = None
    total_sales: float
    order_count: int
    avg_order_value: float
