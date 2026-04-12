from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.inventory import SKU
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.inventory import SKUCreate, SKURead, SKUUpdate

router = APIRouter(prefix="/api/stores/{store_id}/skus", tags=["skus"])


@router.get("", response_model=PaginatedResponse[SKURead])
async def list_skus(
    store_id: UUID,
    page: int = 1,
    page_size: int = 50,
    search: str | None = Query(None, description="Search by SKU code or description"),
    category_id: UUID | None = None,
    brand_id: UUID | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    base = select(SKU).where(SKU.store_id == store_id)
    if search:
        base = base.where(
            SKU.sku_code.ilike(f"%{search}%") | SKU.description.ilike(f"%{search}%")
        )
    if category_id:
        base = base.where(SKU.category_id == category_id)
    if brand_id:
        base = base.where(SKU.brand_id == brand_id)

    count_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = count_result.scalar() or 0

    query = base.order_by(SKU.sku_code).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    skus = result.scalars().all()

    return PaginatedResponse(
        data=[SKURead.model_validate(s) for s in skus],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{sku_id}", response_model=DataResponse[SKURead])
async def get_sku(
    store_id: UUID,
    sku_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SKU).where(SKU.id == sku_id, SKU.store_id == store_id)
    )
    sku = result.scalar_one_or_none()
    if sku is None:
        raise HTTPException(status_code=404, detail="SKU not found")
    return DataResponse(data=SKURead.model_validate(sku))


@router.post("", response_model=DataResponse[SKURead], status_code=201)
async def create_sku(
    store_id: UUID,
    payload: SKUCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = payload.model_dump()
    data["store_id"] = store_id
    sku = SKU(**data)
    db.add(sku)
    await db.flush()
    await db.refresh(sku)
    return DataResponse(data=SKURead.model_validate(sku))


@router.patch("/{sku_id}", response_model=DataResponse[SKURead])
async def update_sku(
    store_id: UUID,
    sku_id: UUID,
    payload: SKUUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SKU).where(SKU.id == sku_id, SKU.store_id == store_id)
    )
    sku = result.scalar_one_or_none()
    if sku is None:
        raise HTTPException(status_code=404, detail="SKU not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(sku, key, value)

    await db.flush()
    await db.refresh(sku)
    return DataResponse(data=SKURead.model_validate(sku))


@router.delete("/{sku_id}", status_code=204)
async def delete_sku(
    store_id: UUID,
    sku_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SKU).where(SKU.id == sku_id, SKU.store_id == store_id)
    )
    sku = result.scalar_one_or_none()
    if sku is None:
        raise HTTPException(status_code=404, detail="SKU not found")
    await db.delete(sku)
