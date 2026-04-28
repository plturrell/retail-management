from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.marketing import (
    CampaignStatusEnum,
    CampaignTypeEnum,
    DiscMethodEnum,
    VoucherStatusEnum,
    VoucherTypeEnum,
)
from app.schemas.common import TimestampMixin, UUIDMixin


# ---------- Campaign ----------

class CampaignBase(BaseModel):
    campaign_code: str = Field(..., max_length=30)
    name: str = Field(..., max_length=255)
    description: str | None = Field(None, max_length=1000)
    campaign_type: CampaignTypeEnum
    start_date: date
    end_date: date
    store_id: UUID | None = None
    budget: float | None = Field(None, ge=0)
    disc_method: DiscMethodEnum | None = None
    disc_value: float | None = Field(None, ge=0)
    points_multiplier: float | None = Field(None, ge=0)
    min_purchase_amount: float | None = Field(None, ge=0)
    max_uses: int | None = Field(None, gt=0)


class CampaignCreate(CampaignBase):
    sku_ids: list[UUID] = []
    category_ids: list[UUID] = []


class CampaignUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    description: str | None = Field(None, max_length=1000)
    status: CampaignStatusEnum | None = None
    start_date: date | None = None
    end_date: date | None = None
    budget: float | None = Field(None, ge=0)
    disc_method: DiscMethodEnum | None = None
    disc_value: float | None = Field(None, ge=0)
    points_multiplier: float | None = Field(None, ge=0)
    min_purchase_amount: float | None = Field(None, ge=0)
    max_uses: int | None = Field(None, gt=0)


class CampaignRead(CampaignBase, UUIDMixin, TimestampMixin):
    status: CampaignStatusEnum
    uses_count: int


# ---------- Voucher ----------

class VoucherBase(BaseModel):
    voucher_code: str = Field(..., max_length=50)
    voucher_type: VoucherTypeEnum
    face_value: float = Field(..., gt=0)
    expiry_date: date | None = None
    issued_to_customer_id: UUID | None = None


class VoucherCreate(VoucherBase):
    issued_at: datetime


class VoucherUpdate(BaseModel):
    status: VoucherStatusEnum | None = None
    expiry_date: date | None = None
    issued_to_customer_id: UUID | None = None


class VoucherRead(VoucherBase, UUIDMixin, TimestampMixin):
    balance: float
    status: VoucherStatusEnum
    issued_by: UUID
    issued_at: datetime
    redeemed_at: datetime | None = None
    redeemed_order_id: UUID | None = None


# ---------- CustomerSegment ----------

class CustomerSegmentBase(BaseModel):
    name: str = Field(..., max_length=255)
    description: str | None = Field(None, max_length=1000)
    criteria: dict[str, Any] | None = None
    is_dynamic: bool = False


class CustomerSegmentCreate(CustomerSegmentBase):
    pass


class CustomerSegmentUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    description: str | None = Field(None, max_length=1000)
    criteria: dict[str, Any] | None = None


class CustomerSegmentRead(CustomerSegmentBase, UUIDMixin, TimestampMixin):
    pass


# ---------- CustomerSegmentMember ----------

class SegmentMemberAdd(BaseModel):
    customer_ids: list[UUID] = Field(..., min_length=1)


class SegmentMemberRead(UUIDMixin):
    segment_id: UUID
    customer_id: UUID
    added_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}
