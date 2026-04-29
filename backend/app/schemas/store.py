from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.store import StoreTypeEnum
from app.schemas.common import TimestampMixin, UUIDMixin


def _normalize_nec_store_id(value: object) -> str | None:
    """Coerce ``nec_store_id`` to either a 5-digit ASCII string or ``None``.

    The value is consumed verbatim by ``cag_export`` to build SFTP
    filenames such as ``SKU_<storeID>_*.txt``; bad values would silently
    produce a broken push or, worse, route a payload to the wrong tenant.
    Mirrors the runtime gate in ``cag_export._validate_nec_store_id`` so
    operators see the failure at PATCH time rather than at push time.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("nec_store_id must be a string of 5 ASCII digits")
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) != 5 or not cleaned.isdigit() or not cleaned.isascii():
        raise ValueError("nec_store_id must be exactly 5 ASCII digits (e.g. 80001)")
    return cleaned


def _normalize_nec_tenant_code(value: object) -> str | None:
    """Coerce ``nec_tenant_code`` to a 6/7-digit Customer No. or ``None``.

    The tenant code becomes a path segment under
    ``Inbound/Working/<tenant>/`` on the SFTP target, so we reject any
    value that is not strictly digits to avoid path-traversal-shaped
    strings.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("nec_tenant_code must be a string of 6 or 7 ASCII digits")
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) not in (6, 7) or not cleaned.isdigit() or not cleaned.isascii():
        raise ValueError(
            "nec_tenant_code must be a 6- or 7-digit Customer No. (e.g. 200151)"
        )
    return cleaned


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
    @field_validator("nec_store_id", mode="before")
    @classmethod
    def _validate_nec_store_id(cls, value: object) -> str | None:
        return _normalize_nec_store_id(value)

    @field_validator("nec_tenant_code", mode="before")
    @classmethod
    def _validate_nec_tenant_code(cls, value: object) -> str | None:
        return _normalize_nec_tenant_code(value)


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

    @field_validator("nec_store_id", mode="before")
    @classmethod
    def _validate_nec_store_id(cls, value: object) -> str | None:
        return _normalize_nec_store_id(value)

    @field_validator("nec_tenant_code", mode="before")
    @classmethod
    def _validate_nec_tenant_code(cls, value: object) -> str | None:
        return _normalize_nec_tenant_code(value)


class StoreRead(StoreBase, UUIDMixin, TimestampMixin):
    store_code: str | None = None
    nec_tenant_code: str | None = None
    nec_store_id: str | None = None
    nec_taxable: bool = True
