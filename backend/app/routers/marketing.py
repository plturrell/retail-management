from __future__ import annotations

import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.marketing import (
    Campaign,
    CampaignCategory,
    CampaignSKU,
    CampaignStatusEnum,
    CustomerSegment,
    CustomerSegmentMember,
    Voucher,
    VoucherStatusEnum,
)
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.marketing import (
    CampaignCreate,
    CampaignRead,
    CampaignUpdate,
    CustomerSegmentCreate,
    CustomerSegmentRead,
    CustomerSegmentUpdate,
    SegmentMemberAdd,
    SegmentMemberRead,
    VoucherCreate,
    VoucherRead,
    VoucherUpdate,
)

router = APIRouter(prefix="/api", tags=["marketing"])

_campaign_router = APIRouter(prefix="/campaigns")
_voucher_router = APIRouter(prefix="/vouchers")
_segment_router = APIRouter(prefix="/customer-segments")


# ------------------------------------------------------------------ #
# Campaigns                                                           #
# ------------------------------------------------------------------ #

@_campaign_router.get("", response_model=PaginatedResponse[CampaignRead])
async def list_campaigns(
    page: int = 1,
    page_size: int = 50,
    status: CampaignStatusEnum | None = None,
    store_id: UUID | None = None,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Campaign)
    if status:
        q = q.where(Campaign.status == status)
    if store_id:
        q = q.where((Campaign.store_id == store_id) | (Campaign.store_id.is_(None)))
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    result = await db.execute(q.order_by(Campaign.start_date.desc()).offset((page - 1) * page_size).limit(page_size))
    return PaginatedResponse(
        data=[CampaignRead.model_validate(c) for c in result.scalars().all()],
        total=total,
        page=page,
        page_size=page_size,
    )


@_campaign_router.get("/{campaign_id}", response_model=DataResponse[CampaignRead])
async def get_campaign(
    campaign_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return DataResponse(data=CampaignRead.model_validate(campaign))


@_campaign_router.post("", response_model=DataResponse[CampaignRead], status_code=201)
async def create_campaign(
    payload: CampaignCreate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sku_ids = payload.sku_ids
    category_ids = payload.category_ids
    campaign_data = payload.model_dump(exclude={"sku_ids", "category_ids"})
    campaign = Campaign(**campaign_data)
    db.add(campaign)
    await db.flush()

    for sku_id in sku_ids:
        db.add(CampaignSKU(campaign_id=campaign.id, sku_id=sku_id))
    for cat_id in category_ids:
        db.add(CampaignCategory(campaign_id=campaign.id, category_id=cat_id))

    await db.flush()
    await db.refresh(campaign)
    return DataResponse(data=CampaignRead.model_validate(campaign))


@_campaign_router.patch("/{campaign_id}", response_model=DataResponse[CampaignRead])
async def update_campaign(
    campaign_id: UUID,
    payload: CampaignUpdate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status == CampaignStatusEnum.ended:
        raise HTTPException(status_code=400, detail="Cannot update an ended campaign")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(campaign, key, value)
    await db.flush()
    await db.refresh(campaign)
    return DataResponse(data=CampaignRead.model_validate(campaign))


@_campaign_router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(
    campaign_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status == CampaignStatusEnum.active:
        raise HTTPException(status_code=400, detail="Pause the campaign before deleting")
    await db.delete(campaign)


# ------------------------------------------------------------------ #
# Vouchers                                                            #
# ------------------------------------------------------------------ #

@_voucher_router.get("", response_model=PaginatedResponse[VoucherRead])
async def list_vouchers(
    page: int = 1,
    page_size: int = 50,
    status: VoucherStatusEnum | None = None,
    customer_id: UUID | None = None,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Voucher)
    if status:
        q = q.where(Voucher.status == status)
    if customer_id:
        q = q.where(Voucher.issued_to_customer_id == customer_id)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    result = await db.execute(q.order_by(Voucher.issued_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return PaginatedResponse(
        data=[VoucherRead.model_validate(v) for v in result.scalars().all()],
        total=total,
        page=page,
        page_size=page_size,
    )


@_voucher_router.get("/{voucher_id}", response_model=DataResponse[VoucherRead])
async def get_voucher(
    voucher_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Voucher).where(Voucher.id == voucher_id))
    voucher = result.scalar_one_or_none()
    if voucher is None:
        raise HTTPException(status_code=404, detail="Voucher not found")
    return DataResponse(data=VoucherRead.model_validate(voucher))


@_voucher_router.get("/lookup/{code}", response_model=DataResponse[VoucherRead])
async def lookup_voucher(
    code: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Voucher).where(Voucher.voucher_code == code))
    voucher = result.scalar_one_or_none()
    if voucher is None:
        raise HTTPException(status_code=404, detail="Voucher not found")
    return DataResponse(data=VoucherRead.model_validate(voucher))


@_voucher_router.post("", response_model=DataResponse[VoucherRead], status_code=201)
async def issue_voucher(
    payload: VoucherCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    voucher = Voucher(
        **payload.model_dump(),
        balance=payload.face_value,
        issued_by=user.id,
    )
    db.add(voucher)
    await db.flush()
    await db.refresh(voucher)
    return DataResponse(data=VoucherRead.model_validate(voucher))


@_voucher_router.patch("/{voucher_id}", response_model=DataResponse[VoucherRead])
async def update_voucher(
    voucher_id: UUID,
    payload: VoucherUpdate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Voucher).where(Voucher.id == voucher_id))
    voucher = result.scalar_one_or_none()
    if voucher is None:
        raise HTTPException(status_code=404, detail="Voucher not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(voucher, key, value)
    await db.flush()
    await db.refresh(voucher)
    return DataResponse(data=VoucherRead.model_validate(voucher))


# ------------------------------------------------------------------ #
# Customer Segments                                                   #
# ------------------------------------------------------------------ #

@_segment_router.get("", response_model=PaginatedResponse[CustomerSegmentRead])
async def list_segments(
    page: int = 1,
    page_size: int = 50,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(CustomerSegment)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    result = await db.execute(q.offset((page - 1) * page_size).limit(page_size))
    return PaginatedResponse(
        data=[CustomerSegmentRead.model_validate(s) for s in result.scalars().all()],
        total=total,
        page=page,
        page_size=page_size,
    )


@_segment_router.post("", response_model=DataResponse[CustomerSegmentRead], status_code=201)
async def create_segment(
    payload: CustomerSegmentCreate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    segment = CustomerSegment(**payload.model_dump())
    db.add(segment)
    await db.flush()
    await db.refresh(segment)
    return DataResponse(data=CustomerSegmentRead.model_validate(segment))


@_segment_router.patch("/{segment_id}", response_model=DataResponse[CustomerSegmentRead])
async def update_segment(
    segment_id: UUID,
    payload: CustomerSegmentUpdate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CustomerSegment).where(CustomerSegment.id == segment_id))
    segment = result.scalar_one_or_none()
    if segment is None:
        raise HTTPException(status_code=404, detail="Segment not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(segment, key, value)
    await db.flush()
    await db.refresh(segment)
    return DataResponse(data=CustomerSegmentRead.model_validate(segment))


@_segment_router.post("/{segment_id}/members", response_model=DataResponse[list[SegmentMemberRead]], status_code=201)
async def add_segment_members(
    segment_id: UUID,
    payload: SegmentMemberAdd,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    members = []
    for customer_id in payload.customer_ids:
        existing = await db.execute(
            select(CustomerSegmentMember).where(
                CustomerSegmentMember.segment_id == segment_id,
                CustomerSegmentMember.customer_id == customer_id,
            )
        )
        if existing.scalar_one_or_none() is None:
            m = CustomerSegmentMember(segment_id=segment_id, customer_id=customer_id, added_at=now)
            db.add(m)
            members.append(m)
    await db.flush()
    for m in members:
        await db.refresh(m)
    return DataResponse(data=[SegmentMemberRead.model_validate(m) for m in members])


@_segment_router.delete("/{segment_id}/members/{customer_id}", status_code=204)
async def remove_segment_member(
    segment_id: UUID,
    customer_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CustomerSegmentMember).where(
            CustomerSegmentMember.segment_id == segment_id,
            CustomerSegmentMember.customer_id == customer_id,
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    await db.delete(member)


# Mount sub-routers
router.include_router(_campaign_router)
router.include_router(_voucher_router)
router.include_router(_segment_router)
