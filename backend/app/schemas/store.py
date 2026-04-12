from __future__ import annotations

from datetime import datetime, time
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import TimestampMixin, UUIDMixin


class StoreBase(BaseModel):
    name: str = Field(..., max_length=255)
    location: str = Field(..., max_length=255)
    address: str = Field(..., max_length=500)
    business_hours_start: time
    business_hours_end: time
    is_active: bool = True


class StoreCreate(StoreBase):
    pass


class StoreUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    location: str | None = Field(None, max_length=255)
    address: str | None = Field(None, max_length=500)
    business_hours_start: time | None = None
    business_hours_end: time | None = None
    is_active: bool | None = None


class StoreRead(StoreBase, UUIDMixin, TimestampMixin):
    pass
