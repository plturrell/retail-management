from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models.customer import AddressTypeEnum, GenderEnum, LoyaltyTierEnum, LoyaltyTransactionTypeEnum
from app.schemas.common import TimestampMixin, UUIDMixin


# ---------- Customer ----------

class CustomerBase(BaseModel):
    customer_code: str = Field(..., max_length=30)
    first_name: str = Field(..., max_length=100)
    last_name: str = Field(..., max_length=100)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    date_of_birth: date | None = None
    gender: GenderEnum | None = None
    is_active: bool = True
    notes: str | None = Field(None, max_length=1000)


class CustomerCreate(CustomerBase):
    registered_store_id: UUID | None = None


class CustomerUpdate(BaseModel):
    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    date_of_birth: date | None = None
    gender: GenderEnum | None = None
    is_active: bool | None = None
    notes: str | None = Field(None, max_length=1000)


class CustomerRead(CustomerBase, UUIDMixin, TimestampMixin):
    registered_store_id: UUID | None = None


# ---------- CustomerAddress ----------

class CustomerAddressBase(BaseModel):
    address_type: AddressTypeEnum = AddressTypeEnum.home
    address_line1: str = Field(..., max_length=255)
    address_line2: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=100)
    country: str = Field("Singapore", max_length=100)
    postal_code: str | None = Field(None, max_length=20)
    is_default: bool = False


class CustomerAddressCreate(CustomerAddressBase):
    customer_id: UUID


class CustomerAddressUpdate(BaseModel):
    address_type: AddressTypeEnum | None = None
    address_line1: str | None = Field(None, max_length=255)
    address_line2: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=100)
    country: str | None = Field(None, max_length=100)
    postal_code: str | None = Field(None, max_length=20)
    is_default: bool | None = None


class CustomerAddressRead(CustomerAddressBase, UUIDMixin, TimestampMixin):
    customer_id: UUID


# ---------- LoyaltyAccount ----------

class LoyaltyAccountRead(UUIDMixin, TimestampMixin):
    customer_id: UUID
    tier: LoyaltyTierEnum
    points_balance: int
    lifetime_points: int
    joined_date: date


class LoyaltyAccountCreate(BaseModel):
    customer_id: UUID
    joined_date: date


# ---------- LoyaltyTransaction ----------

class LoyaltyTransactionCreate(BaseModel):
    transaction_type: LoyaltyTransactionTypeEnum
    points: int
    reference_type: str | None = Field(None, max_length=50)
    reference_id: str | None = Field(None, max_length=100)
    notes: str | None = Field(None, max_length=500)


class LoyaltyTransactionRead(LoyaltyTransactionCreate, UUIDMixin):
    loyalty_account_id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}
