from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.store import StoreTypeEnum
from app.schemas.common import TimestampMixin, UUIDMixin


class StoreType(str, Enum):
    flagship = "flagship"
    outlet = "outlet"
    pop_up = "pop_up"
    retail = "retail"
    warehouse = "warehouse"
    online = "online"
    hybrid = "hybrid"


class StoreOperationalStatus(str, Enum):
    active = "active"
    staging = "staging"
    planned = "planned"
    inactive = "inactive"


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
    store_type: StoreType = StoreType.retail
    operational_status: StoreOperationalStatus = StoreOperationalStatus.active
    is_home_base: bool = False
    is_temp_warehouse: bool = False
    planned_open_date: date | None = None
    notes: str | None = Field(None, max_length=1000)
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
    store_type: StoreType | None = None
    operational_status: StoreOperationalStatus | None = None
    is_home_base: bool | None = None
    is_temp_warehouse: bool | None = None
    planned_open_date: date | None = None
    notes: str | None = Field(None, max_length=1000)
    is_active: bool | None = None


class StoreRead(StoreBase, UUIDMixin, TimestampMixin):
    store_code: str | None = None
