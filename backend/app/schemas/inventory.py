from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import TimestampMixin, UUIDMixin


# ---------- Category ----------

class CategoryBase(BaseModel):
    catg_code: str = Field(..., max_length=50)
    cag_catg_code: str | None = Field(None, max_length=50)
    description: str = Field(..., max_length=255)
    parent_id: UUID | None = None


class CategoryCreate(CategoryBase):
    store_id: UUID


class CategoryUpdate(BaseModel):
    catg_code: str | None = Field(None, max_length=50)
    cag_catg_code: str | None = Field(None, max_length=50)
    description: str | None = Field(None, max_length=255)
    parent_id: UUID | None = None


class CategoryRead(CategoryBase, UUIDMixin, TimestampMixin):
    store_id: UUID


# ---------- Brand ----------

class BrandBase(BaseModel):
    name: str = Field(..., max_length=255)
    category_type: str | None = Field(None, max_length=100)


class BrandCreate(BrandBase):
    pass


class BrandUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    category_type: str | None = Field(None, max_length=100)


class BrandRead(BrandBase, UUIDMixin):
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ---------- SKU ----------

class SKUBase(BaseModel):
    sku_code: str = Field(..., max_length=32)
    description: str = Field(..., max_length=60)
    long_description: str | None = Field(None, max_length=1000)
    cost_price: float | None = None
    category_id: UUID | None = None
    brand_id: UUID | None = None
    tax_code: str = Field("G", max_length=1)
    gender: str | None = Field(None, max_length=20)
    age_group: str | None = Field(None, max_length=20)
    is_unique_piece: bool = False
    use_stock: bool = True
    block_sales: bool = False
    product_type: str = Field("finished", max_length=20)
    attributes: dict | None = None
    status: str = Field("active", max_length=20)


class SKUCreate(SKUBase):
    store_id: UUID


class SKUUpdate(BaseModel):
    description: str | None = Field(None, max_length=60)
    long_description: str | None = Field(None, max_length=1000)
    cost_price: float | None = None
    category_id: UUID | None = None
    brand_id: UUID | None = None
    tax_code: str | None = Field(None, max_length=1)
    gender: str | None = Field(None, max_length=20)
    age_group: str | None = Field(None, max_length=20)
    is_unique_piece: bool | None = None
    use_stock: bool | None = None
    block_sales: bool | None = None
    product_type: str | None = Field(None, max_length=20)
    attributes: dict | None = None
    status: str | None = Field(None, max_length=20)


class SKURead(SKUBase, UUIDMixin, TimestampMixin):
    store_id: UUID


# ---------- PLU ----------

class PLUBase(BaseModel):
    plu_code: str = Field(..., max_length=20)
    sku_id: UUID


class PLUCreate(PLUBase):
    pass


class PLURead(PLUBase, UUIDMixin):
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ---------- Price ----------

class PriceBase(BaseModel):
    sku_id: UUID
    store_id: UUID | None = None
    price_incl_tax: float
    price_excl_tax: float
    price_unit: int = 1
    valid_from: date
    valid_to: date


class PriceCreate(PriceBase):
    pass


class PriceUpdate(BaseModel):
    price_incl_tax: float | None = None
    price_excl_tax: float | None = None
    price_unit: int | None = None
    valid_from: date | None = None
    valid_to: date | None = None


class PriceRead(PriceBase, UUIDMixin, TimestampMixin):
    pass


# ---------- Promotion ----------

class PromotionBase(BaseModel):
    disc_id: str = Field(..., max_length=20)
    sku_id: UUID | None = None
    category_id: UUID | None = None
    line_type: str = Field(..., max_length=20)
    disc_method: str = Field(..., max_length=20)
    disc_value: float
    line_group: str | None = Field(None, max_length=1)


class PromotionCreate(PromotionBase):
    pass


class PromotionUpdate(BaseModel):
    disc_method: str | None = Field(None, max_length=20)
    disc_value: float | None = None
    line_group: str | None = Field(None, max_length=1)


class PromotionRead(PromotionBase, UUIDMixin, TimestampMixin):
    pass


# ---------- Inventory ----------

class InventoryBase(BaseModel):
    sku_id: UUID
    store_id: UUID
    qty_on_hand: int = 0
    reorder_level: int = 0
    reorder_qty: int = 0
    serial_number: str | None = Field(None, max_length=255)


class InventoryCreate(InventoryBase):
    pass


class InventoryUpdate(BaseModel):
    qty_on_hand: int | None = None
    reorder_level: int | None = None
    reorder_qty: int | None = None
    serial_number: str | None = Field(None, max_length=255)


class InventoryRead(InventoryBase, UUIDMixin, TimestampMixin):
    last_updated: datetime
