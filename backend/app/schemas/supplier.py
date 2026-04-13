from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import TimestampMixin, UUIDMixin


# ---------- Supplier ----------

class SupplierBase(BaseModel):
    supplier_code: str = Field(..., max_length=30)
    name: str = Field(..., max_length=255)
    contact_person: str | None = Field(None, max_length=255)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    address: str | None = Field(None, max_length=500)
    country: str = Field("Singapore", max_length=100)
    currency: str = Field("SGD", max_length=3)
    payment_terms_days: int = 30
    gst_registered: bool = False
    gst_number: str | None = Field(None, max_length=50)
    bank_account: str | None = Field(None, max_length=50)
    bank_name: str | None = Field(None, max_length=100)
    notes: str | None = Field(None, max_length=1000)
    is_active: bool = True


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    contact_person: str | None = Field(None, max_length=255)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    address: str | None = Field(None, max_length=500)
    country: str | None = Field(None, max_length=100)
    currency: str | None = Field(None, max_length=3)
    payment_terms_days: int | None = None
    gst_registered: bool | None = None
    gst_number: str | None = Field(None, max_length=50)
    bank_account: str | None = Field(None, max_length=50)
    bank_name: str | None = Field(None, max_length=100)
    notes: str | None = Field(None, max_length=1000)
    is_active: bool | None = None


class SupplierRead(SupplierBase, UUIDMixin, TimestampMixin):
    pass


# ---------- SupplierProduct ----------

class SupplierProductBase(BaseModel):
    supplier_id: UUID
    sku_id: UUID
    supplier_sku_code: str | None = Field(None, max_length=100)
    supplier_unit_cost: float
    currency: str = Field("SGD", max_length=3)
    min_order_qty: int = 1
    lead_time_days: int = 7
    is_preferred: bool = False


class SupplierProductCreate(SupplierProductBase):
    pass


class SupplierProductUpdate(BaseModel):
    supplier_sku_code: str | None = Field(None, max_length=100)
    supplier_unit_cost: float | None = None
    currency: str | None = Field(None, max_length=3)
    min_order_qty: int | None = None
    lead_time_days: int | None = None
    is_preferred: bool | None = None


class SupplierProductRead(SupplierProductBase, UUIDMixin, TimestampMixin):
    pass
