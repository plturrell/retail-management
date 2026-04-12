import uuid
from datetime import date, datetime
from typing import Optional
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models._mixins import uuid_pk, created_at_col, updated_at_col


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[uuid_pk]
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True
    )
    catg_code: Mapped[str] = mapped_column(String(50), nullable=False)
    cag_catg_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    parent = relationship("Category", remote_side="Category.id", lazy="selectin")
    store = relationship("Store", back_populates="categories", lazy="selectin")
    skus = relationship("SKU", back_populates="category", lazy="selectin")
    promotions = relationship("Promotion", back_populates="category", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Category {self.catg_code}: {self.description}>"


class Brand(Base):
    __tablename__ = "brands"

    id: Mapped[uuid_pk]
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[created_at_col]

    # Relationships
    skus = relationship("SKU", back_populates="brand", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Brand {self.name}>"


class SKU(Base):
    __tablename__ = "skus"

    id: Mapped[uuid_pk]
    sku_code: Mapped[str] = mapped_column(
        String(16), unique=True, index=True, nullable=False
    )
    description: Mapped[str] = mapped_column(String(60), nullable=False)
    long_description: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    cost_price: Mapped[Optional[float]] = mapped_column(Numeric(20, 2), nullable=True)
    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True
    )
    brand_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brands.id"), nullable=True
    )
    tax_code: Mapped[str] = mapped_column(String(1), nullable=False, default="G")
    gender: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    age_group: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_unique_piece: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    use_stock: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    block_sales: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    category = relationship("Category", back_populates="skus", lazy="selectin")
    brand = relationship("Brand", back_populates="skus", lazy="selectin")
    store = relationship("Store", back_populates="skus", lazy="selectin")
    plus = relationship("PLU", back_populates="sku", lazy="selectin")
    prices = relationship("Price", back_populates="sku", lazy="selectin")
    promotions = relationship("Promotion", back_populates="sku", lazy="selectin")
    inventories = relationship("Inventory", back_populates="sku", lazy="selectin")
    order_items = relationship("OrderItem", back_populates="sku", lazy="selectin")

    def __repr__(self) -> str:
        return f"<SKU {self.sku_code}: {self.description}>"


class PLU(Base):
    __tablename__ = "plus"

    id: Mapped[uuid_pk]
    plu_code: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, nullable=False
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[created_at_col]

    # Relationships
    sku = relationship("SKU", back_populates="plus", lazy="selectin")

    def __repr__(self) -> str:
        return f"<PLU {self.plu_code}>"


class Price(Base):
    __tablename__ = "prices"

    id: Mapped[uuid_pk]
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id", ondelete="CASCADE"), nullable=False
    )
    store_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=True
    )
    price_incl_tax: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    price_excl_tax: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    price_unit: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    sku = relationship("SKU", back_populates="prices", lazy="selectin")
    store = relationship("Store", back_populates="prices", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Price SKU={self.sku_id} ${self.price_incl_tax}>"


class Promotion(Base):
    __tablename__ = "promotions"

    id: Mapped[uuid_pk]
    disc_id: Mapped[str] = mapped_column(String(20), nullable=False)
    sku_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id", ondelete="CASCADE"), nullable=True
    )
    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="CASCADE"),
        nullable=True,
    )
    line_type: Mapped[str] = mapped_column(String(20), nullable=False)
    disc_method: Mapped[str] = mapped_column(String(20), nullable=False)
    disc_value: Mapped[float] = mapped_column(Numeric(11, 2), nullable=False)
    line_group: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    sku = relationship("SKU", back_populates="promotions", lazy="selectin")
    category = relationship("Category", back_populates="promotions", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Promotion {self.disc_id}>"


class Inventory(Base):
    __tablename__ = "inventories"

    id: Mapped[uuid_pk]
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id", ondelete="CASCADE"), nullable=False
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    qty_on_hand: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reorder_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reorder_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    serial_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_updated: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    sku = relationship("SKU", back_populates="inventories", lazy="selectin")
    store = relationship("Store", back_populates="inventories", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Inventory SKU={self.sku_id} qty={self.qty_on_hand}>"
