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
    UniqueConstraint,
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum
from app.database import Base
from app.models._mixins import uuid_pk, created_at_col, updated_at_col

# Forward-declare enums used on Inventory (defined in copilot.py to avoid circular imports)
_INVENTORY_TYPE_ENUM = "inventory_type_enum"
_SOURCING_STRATEGY_ENUM = "sourcing_strategy_enum"


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
    parent = relationship("Category", remote_side="Category.id", lazy="raise")
    store = relationship("Store", back_populates="categories", lazy="raise")
    skus = relationship("SKU", back_populates="category", lazy="raise")
    promotions = relationship("Promotion", back_populates="category", lazy="raise")

    def __repr__(self) -> str:
        return f"<Category {self.catg_code}: {self.description}>"


class Brand(Base):
    __tablename__ = "brands"

    id: Mapped[uuid_pk]
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[created_at_col]

    # Relationships
    skus = relationship("SKU", back_populates="brand", lazy="raise")

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
    category = relationship("Category", back_populates="skus", lazy="raise")
    brand = relationship("Brand", back_populates="skus", lazy="raise")
    store = relationship("Store", back_populates="skus", lazy="raise")
    plus = relationship("PLU", back_populates="sku", lazy="raise")
    prices = relationship("Price", back_populates="sku", lazy="raise")
    promotions = relationship("Promotion", back_populates="sku", lazy="raise")
    inventories = relationship("Inventory", back_populates="sku", lazy="raise")
    order_items = relationship("OrderItem", back_populates="sku", lazy="raise")

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
    sku = relationship("SKU", back_populates="plus", lazy="raise")

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
    sku = relationship("SKU", back_populates="prices", lazy="raise")
    store = relationship("Store", back_populates="prices", lazy="raise")

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
    sku = relationship("SKU", back_populates="promotions", lazy="raise")
    category = relationship("Category", back_populates="promotions", lazy="raise")

    def __repr__(self) -> str:
        return f"<Promotion {self.disc_id}>"


class InventoryLocationState(str, enum.Enum):
    STORE = "STORE"
    TRANSIT = "TRANSIT"
    WORKSHOP = "WORKSHOP"
    DECOR = "DECOR"


class Inventory(Base):
    __tablename__ = "inventories"
    __table_args__ = (
        UniqueConstraint("store_id", "sku_id", name="uq_inventory_store_sku"),
    )

    id: Mapped[uuid_pk]
    location_status: Mapped[InventoryLocationState] = mapped_column(
        SQLEnum(InventoryLocationState, name="inventory_location_enum"), 
        default=InventoryLocationState.STORE, 
        nullable=False
    )
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
    # Copilot fields
    inventory_type: Mapped[str] = mapped_column(
        SQLEnum("purchased", "material", "finished", name=_INVENTORY_TYPE_ENUM, create_type=False),
        nullable=False, default="purchased",
    )
    sourcing_strategy: Mapped[str] = mapped_column(
        SQLEnum("supplier_premade", "manufactured_standard", "manufactured_custom",
                name=_SOURCING_STRATEGY_ENUM, create_type=False),
        nullable=False, default="supplier_premade",
    )
    primary_supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    sku = relationship("SKU", back_populates="inventories", lazy="raise")
    store = relationship("Store", back_populates="inventories", lazy="raise")

    def __repr__(self) -> str:
        return f"<Inventory SKU={self.sku_id} qty={self.qty_on_hand}>"
