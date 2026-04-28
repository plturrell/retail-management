from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.purchase import (
    ExpenseStatus,
    GoodsConditionEnum,
    GoodsReceiptStatus,
    PurchaseOrderStatus,
)
from app.schemas.common import TimestampMixin, UUIDMixin


# ---------- PurchaseOrderItem ----------

class PurchaseOrderItemBase(BaseModel):
    sku_id: UUID
    qty_ordered: int = Field(..., gt=0)
    unit_cost: float = Field(..., gt=0)
    tax_code: str = Field("G", max_length=1)

    @property
    def line_total(self) -> float:
        return self.qty_ordered * self.unit_cost


class PurchaseOrderItemCreate(PurchaseOrderItemBase):
    pass


class PurchaseOrderItemRead(PurchaseOrderItemBase, UUIDMixin, TimestampMixin):
    purchase_order_id: UUID
    qty_received: int
    line_total: float


# ---------- PurchaseOrder ----------

class PurchaseOrderBase(BaseModel):
    store_id: UUID
    supplier_id: UUID
    order_date: date
    expected_delivery_date: date | None = None
    currency: str = Field("SGD", max_length=3)
    notes: str | None = Field(None, max_length=1000)


class PurchaseOrderCreate(PurchaseOrderBase):
    items: list[PurchaseOrderItemCreate] = Field(..., min_length=1)


class PurchaseOrderUpdate(BaseModel):
    expected_delivery_date: date | None = None
    status: PurchaseOrderStatus | None = None
    notes: str | None = Field(None, max_length=1000)


class PurchaseOrderRead(PurchaseOrderBase, UUIDMixin, TimestampMixin):
    status: PurchaseOrderStatus
    subtotal: float
    tax_total: float
    grand_total: float
    created_by: UUID
    items: list[PurchaseOrderItemRead] = []


# ---------- GoodsReceiptItem ----------

class GoodsReceiptItemBase(BaseModel):
    po_item_id: UUID
    sku_id: UUID
    qty_received: int = Field(..., gt=0)
    condition: GoodsConditionEnum = GoodsConditionEnum.good
    notes: str | None = Field(None, max_length=500)


class GoodsReceiptItemCreate(GoodsReceiptItemBase):
    pass


class GoodsReceiptItemRead(GoodsReceiptItemBase, UUIDMixin):
    goods_receipt_id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------- GoodsReceipt ----------

class GoodsReceiptBase(BaseModel):
    purchase_order_id: UUID
    store_id: UUID
    received_date: date
    notes: str | None = Field(None, max_length=1000)


class GoodsReceiptCreate(GoodsReceiptBase):
    items: list[GoodsReceiptItemCreate] = Field(..., min_length=1)


class GoodsReceiptUpdate(BaseModel):
    notes: str | None = Field(None, max_length=1000)
    status: GoodsReceiptStatus | None = None


class GoodsReceiptRead(GoodsReceiptBase, UUIDMixin, TimestampMixin):
    grn_number: str
    received_by: UUID
    status: GoodsReceiptStatus
    items: list[GoodsReceiptItemRead] = []


# ---------- ExpenseCategory ----------

class ExpenseCategoryBase(BaseModel):
    code: str = Field(..., max_length=20)
    name: str = Field(..., max_length=255)
    account_id: UUID | None = None
    is_active: bool = True


class ExpenseCategoryCreate(ExpenseCategoryBase):
    pass


class ExpenseCategoryUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    account_id: UUID | None = None
    is_active: bool | None = None


class ExpenseCategoryRead(ExpenseCategoryBase, UUIDMixin, TimestampMixin):
    pass


# ---------- Expense ----------

class ExpenseBase(BaseModel):
    store_id: UUID
    category_id: UUID
    vendor_name: str | None = Field(None, max_length=255)
    expense_date: date
    amount_excl_tax: float = Field(..., ge=0)
    tax_amount: float = Field(0.0, ge=0)
    amount_incl_tax: float = Field(..., ge=0)
    payment_method: str | None = Field(None, max_length=50)
    payment_ref: str | None = Field(None, max_length=255)
    description: str = Field(..., max_length=500)
    receipt_url: str | None = Field(None, max_length=1000)


class ExpenseCreate(ExpenseBase):
    pass


class ExpenseUpdate(BaseModel):
    vendor_name: str | None = Field(None, max_length=255)
    expense_date: date | None = None
    amount_excl_tax: float | None = Field(None, ge=0)
    tax_amount: float | None = Field(None, ge=0)
    amount_incl_tax: float | None = Field(None, ge=0)
    payment_method: str | None = Field(None, max_length=50)
    payment_ref: str | None = Field(None, max_length=255)
    description: str | None = Field(None, max_length=500)
    receipt_url: str | None = Field(None, max_length=1000)
    status: ExpenseStatus | None = None


class ExpenseRead(ExpenseBase, UUIDMixin, TimestampMixin):
    expense_number: str
    status: ExpenseStatus
    submitted_by: UUID
    approved_by: UUID | None = None
    approved_at: datetime | None = None
