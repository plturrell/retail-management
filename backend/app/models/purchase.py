import enum
import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._mixins import uuid_pk, created_at_col, updated_at_col


class PurchaseOrderStatus(str, enum.Enum):
    draft = "draft"
    submitted = "submitted"
    confirmed = "confirmed"
    partially_received = "partially_received"
    fully_received = "fully_received"
    cancelled = "cancelled"


class GoodsReceiptStatus(str, enum.Enum):
    pending = "pending"
    partial = "partial"
    complete = "complete"


class GoodsConditionEnum(str, enum.Enum):
    good = "good"
    damaged = "damaged"
    rejected = "rejected"


class ExpenseStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    paid = "paid"
    rejected = "rejected"


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[uuid_pk]
    po_number: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False
    )
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_delivery_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        SQLEnum(PurchaseOrderStatus, name="po_status_enum"),
        default=PurchaseOrderStatus.draft,
        nullable=False,
    )
    subtotal: Mapped[float] = mapped_column(Numeric(20, 2), default=0, nullable=False)
    tax_total: Mapped[float] = mapped_column(Numeric(20, 2), default=0, nullable=False)
    grand_total: Mapped[float] = mapped_column(Numeric(20, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="SGD", nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    store = relationship("Store", lazy="raise")
    supplier = relationship("Supplier", back_populates="purchase_orders", lazy="raise")
    creator = relationship("User", lazy="raise")
    items = relationship(
        "PurchaseOrderItem",
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    goods_receipts = relationship(
        "GoodsReceipt", back_populates="purchase_order", lazy="raise"
    )

    def __repr__(self) -> str:
        return f"<PurchaseOrder {self.po_number} status={self.status}>"


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    id: Mapped[uuid_pk]
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id"), nullable=False
    )
    qty_ordered: Mapped[int] = mapped_column(Integer, nullable=False)
    qty_received: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unit_cost: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    tax_code: Mapped[str] = mapped_column(String(1), default="G", nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="items", lazy="raise")
    sku = relationship("SKU", lazy="raise")
    receipt_items = relationship("GoodsReceiptItem", back_populates="po_item", lazy="raise")

    def __repr__(self) -> str:
        return f"<PurchaseOrderItem po={self.purchase_order_id} sku={self.sku_id} qty={self.qty_ordered}>"


class GoodsReceipt(Base):
    __tablename__ = "goods_receipts"

    id: Mapped[uuid_pk]
    grn_number: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    received_date: Mapped[date] = mapped_column(Date, nullable=False)
    received_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[GoodsReceiptStatus] = mapped_column(
        SQLEnum(GoodsReceiptStatus, name="grn_status_enum"),
        default=GoodsReceiptStatus.pending,
        nullable=False,
    )
    notes: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    purchase_order = relationship(
        "PurchaseOrder", back_populates="goods_receipts", lazy="raise"
    )
    store = relationship("Store", lazy="raise")
    receiver = relationship("User", lazy="raise")
    items = relationship(
        "GoodsReceiptItem",
        back_populates="goods_receipt",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<GoodsReceipt {self.grn_number} status={self.status}>"


class GoodsReceiptItem(Base):
    __tablename__ = "goods_receipt_items"

    id: Mapped[uuid_pk]
    goods_receipt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("goods_receipts.id", ondelete="CASCADE"),
        nullable=False,
    )
    po_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_order_items.id"),
        nullable=False,
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id"), nullable=False
    )
    qty_received: Mapped[int] = mapped_column(Integer, nullable=False)
    condition: Mapped[GoodsConditionEnum] = mapped_column(
        SQLEnum(GoodsConditionEnum, name="goods_condition_enum"),
        default=GoodsConditionEnum.good,
        nullable=False,
    )
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[created_at_col]

    # Relationships
    goods_receipt = relationship("GoodsReceipt", back_populates="items", lazy="raise")
    po_item = relationship("PurchaseOrderItem", back_populates="receipt_items", lazy="raise")
    sku = relationship("SKU", lazy="raise")

    def __repr__(self) -> str:
        return f"<GoodsReceiptItem grn={self.goods_receipt_id} sku={self.sku_id} qty={self.qty_received}>"


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"

    id: Mapped[uuid_pk]
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Links to GL account for automatic journal posting
    account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    account = relationship("Account", lazy="raise")
    expenses = relationship("Expense", back_populates="category", lazy="raise")

    def __repr__(self) -> str:
        return f"<ExpenseCategory {self.code}: {self.name}>"


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[uuid_pk]
    expense_number: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("expense_categories.id"), nullable=False
    )
    vendor_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_excl_tax: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    tax_amount: Mapped[float] = mapped_column(Numeric(20, 2), default=0, nullable=False)
    amount_incl_tax: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payment_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    receipt_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    status: Mapped[ExpenseStatus] = mapped_column(
        SQLEnum(ExpenseStatus, name="expense_status_enum"),
        default=ExpenseStatus.pending,
        nullable=False,
    )
    submitted_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    store = relationship("Store", lazy="raise")
    category = relationship("ExpenseCategory", back_populates="expenses", lazy="raise")
    submitter = relationship("User", foreign_keys=[submitted_by], lazy="raise")
    approver = relationship("User", foreign_keys=[approved_by], lazy="raise")

    def __repr__(self) -> str:
        return f"<Expense {self.expense_number} ${self.amount_incl_tax} status={self.status}>"
