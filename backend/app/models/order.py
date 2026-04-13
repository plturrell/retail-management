import enum
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models._mixins import uuid_pk, created_at_col, updated_at_col


class OrderStatus(str, enum.Enum):
    open = "open"
    completed = "completed"
    voided = "voided"


class OrderSource(str, enum.Enum):
    nec_pos = "nec_pos"
    hipay = "hipay"
    airwallex = "airwallex"
    shopify = "shopify"
    manual = "manual"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid_pk]
    order_number: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    staff_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    salesperson_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    order_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    subtotal: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    discount_total: Mapped[float] = mapped_column(
        Numeric(20, 2), default=0, nullable=False
    )
    tax_total: Mapped[float] = mapped_column(
        Numeric(20, 2), default=0, nullable=False
    )
    grand_total: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(50), nullable=False)
    payment_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status_enum"), nullable=False
    )
    source: Mapped[OrderSource] = mapped_column(
        Enum(OrderSource, name="order_source_enum"), nullable=False
    )
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    store = relationship("Store", back_populates="orders", lazy="raise")
    staff = relationship("User", back_populates="orders", foreign_keys=[staff_id], lazy="raise")
    salesperson = relationship("User", foreign_keys=[salesperson_id], lazy="raise")
    items = relationship("OrderItem", back_populates="order", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Order {self.order_number}>"


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid_pk]
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id"), nullable=False
    )
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    discount: Mapped[float] = mapped_column(
        Numeric(20, 2), default=0, nullable=False
    )
    line_total: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    created_at: Mapped[created_at_col]

    # Relationships
    order = relationship("Order", back_populates="items", lazy="raise")
    sku = relationship("SKU", back_populates="order_items", lazy="raise")

    def __repr__(self) -> str:
        return f"<OrderItem order={self.order_id} sku={self.sku_id} qty={self.qty}>"


class SalespersonAlias(Base):
    __tablename__ = "salesperson_aliases"

    id: Mapped[uuid_pk]
    alias_name: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[created_at_col]

    # Relationships
    user = relationship("User", lazy="raise")
    store = relationship("Store", lazy="raise")

    def __repr__(self) -> str:
        return f"<SalespersonAlias {self.alias_name} -> user={self.user_id}>"
