import uuid
from typing import Optional

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._mixins import uuid_pk, created_at_col, updated_at_col


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[uuid_pk]
    supplier_code: Mapped[str] = mapped_column(
        String(30), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_person: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    country: Mapped[str] = mapped_column(String(100), default="Singapore", nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="SGD", nullable=False)
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    gst_registered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    gst_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    bank_account: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    bank_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    products = relationship("SupplierProduct", back_populates="supplier", lazy="raise")
    purchase_orders = relationship("PurchaseOrder", back_populates="supplier", lazy="raise")

    def __repr__(self) -> str:
        return f"<Supplier {self.supplier_code}: {self.name}>"


class SupplierProduct(Base):
    """Maps a supplier's product to our internal SKU."""

    __tablename__ = "supplier_products"

    id: Mapped[uuid_pk]
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id", ondelete="CASCADE"), nullable=False
    )
    supplier_sku_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    supplier_unit_cost: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="SGD", nullable=False)
    min_order_qty: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    supplier = relationship("Supplier", back_populates="products", lazy="raise")
    sku = relationship("SKU", lazy="raise")

    def __repr__(self) -> str:
        return f"<SupplierProduct supplier={self.supplier_id} sku={self.sku_id}>"
