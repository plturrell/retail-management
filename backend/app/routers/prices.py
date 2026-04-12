from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.inventory import Price
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.inventory import PriceCreate, PriceRead, PriceUpdate

router = APIRouter(prefix="/api/stores/{store_id}/prices", tags=["prices"])


@router.get("", response_model=PaginatedResponse[PriceRead])
async def list_prices(
    store_id: UUID,
    sku_id: UUID | None = None,
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    base = select(Price).where(Price.store_id == store_id)
    if sku_id:
        base = base.where(Price.sku_id == sku_id)

    count_result = await db.execute(select(Price.id).where(Price.store_id == store_id))
    total = len(count_result.all())

    query = base.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    prices = result.scalars().all()

    return PaginatedResponse(
        data=[PriceRead.model_validate(p) for p in prices],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=DataResponse[PriceRead], status_code=201)
async def create_price(
    store_id: UUID,
    payload: PriceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = payload.model_dump()
    data["store_id"] = store_id
    price = Price(**data)
    db.add(price)
    await db.flush()
    await db.refresh(price)
    return DataResponse(data=PriceRead.model_validate(price))


@router.patch("/{price_id}", response_model=DataResponse[PriceRead])
async def update_price(
    store_id: UUID,
    price_id: UUID,
    payload: PriceUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Price).where(Price.id == price_id, Price.store_id == store_id)
    )
    price = result.scalar_one_or_none()
    if price is None:
        raise HTTPException(status_code=404, detail="Price not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(price, key, value)

    await db.flush()
    await db.refresh(price)
    return DataResponse(data=PriceRead.model_validate(price))


@router.delete("/{price_id}", status_code=204)
async def delete_price(
    store_id: UUID,
    price_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Price).where(Price.id == price_id, Price.store_id == store_id)
    )
    price = result.scalar_one_or_none()
    if price is None:
        raise HTTPException(status_code=404, detail="Price not found")
    await db.delete(price)
