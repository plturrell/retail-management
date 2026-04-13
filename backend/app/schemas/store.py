from __future__ import annotations

from datetime import datetime, time
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.store import StoreTypeEnum
from app.schemas.common import TimestampMixin, UUIDMixin


class StoreBase(BaseModel):
    store_code: str = Field(..., max_length=20)
    name: str = Field(..., max_length=255)
    store_type: StoreTypeEnum = StoreTypeEnum.outlet
    location: str = Field(..., max_length=255)
    address: str = Field(..., max_length=500)
    city: str = Field("Singapore", max_length=100)
    country: str = Field("Singapore", max_length=100)
    postal_code: str | None = Field(None, max_length=20)
    phone: str | None = Field(None, max_length=50)
    email: str | None = Field(None, max_length=255)
    currency: str = Field("SGD", max_length=3)
    business_hours_start: time
    business_hours_end: time
    is_active: bool = True


class StoreCreate(StoreBase):
    pass


class StoreUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    store_type: StoreTypeEnum | None = None
    location: str | None = Field(None, max_length=255)
    address: str | None = Field(None, max_length=500)
    city: str | None = Field(None, max_length=100)
    country: str | None = Field(None, max_length=100)
    postal_code: str | None = Field(None, max_length=20)
    phone: str | None = Field(None, max_length=50)
    email: str | None = Field(None, max_length=255)
    currency: str | None = Field(None, max_length=3)
    business_hours_start: time | None = None
    business_hours_end: time | None = None
    is_active: bool | None = None


class StoreRead(StoreBase, UUIDMixin, TimestampMixin):
    pass
