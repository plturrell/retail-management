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
    # CAG / NEC Jewel POS integration. ``nec_tenant_code`` overrides the
    # global tenant folder when this store belongs to a different legal
    # entity. ``nec_store_id`` is the 5-digit Store ID assigned by NEC and
    # used for ``SKU_<storeID>_*.txt`` / ``INVDETAILS_<storeID>_*.txt``.
    # ``nec_taxable`` toggles ``TAX_CODE`` between ``G`` (landside) and
    # ``N`` (airside) — see ``CAG-Jewel-ISD-Interfaces TXT Formats v1.7.6j``.
    nec_tenant_code: str | None = Field(None, max_length=20)
    nec_store_id: str | None = Field(None, max_length=5)
    nec_taxable: bool = True


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
    nec_tenant_code: str | None = Field(None, max_length=20)
    nec_store_id: str | None = Field(None, max_length=5)
    nec_taxable: bool | None = None


class StoreRead(StoreBase, UUIDMixin, TimestampMixin):
    store_code: str | None = None
    nec_tenant_code: str | None = None
    nec_store_id: str | None = None
    nec_taxable: bool = True
