from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.inventory import Brand
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.inventory import BrandCreate, BrandRead, BrandUpdate

router = APIRouter(prefix="/api/brands", tags=["brands"])


@router.get("", response_model=PaginatedResponse[BrandRead])
async def list_brands(
    page: int = 1,
    page_size: int = 100,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    count_result = await db.execute(select(func.count()).select_from(Brand))
    total = count_result.scalar() or 0

    query = select(Brand).order_by(Brand.name).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    brands = result.scalars().all()

    return PaginatedResponse(
        data=[BrandRead.model_validate(b) for b in brands],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{brand_id}", response_model=DataResponse[BrandRead])
async def get_brand(
    brand_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Brand).where(Brand.id == brand_id))
    brand = result.scalar_one_or_none()
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    return DataResponse(data=BrandRead.model_validate(brand))


@router.post("", response_model=DataResponse[BrandRead], status_code=201)
async def create_brand(
    payload: BrandCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    brand = Brand(**payload.model_dump())
    db.add(brand)
    await db.flush()
    await db.refresh(brand)
    return DataResponse(data=BrandRead.model_validate(brand))


@router.patch("/{brand_id}", response_model=DataResponse[BrandRead])
async def update_brand(
    brand_id: UUID,
    payload: BrandUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Brand).where(Brand.id == brand_id))
    brand = result.scalar_one_or_none()
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(brand, key, value)

    await db.flush()
    await db.refresh(brand)
    return DataResponse(data=BrandRead.model_validate(brand))


@router.delete("/{brand_id}", status_code=204)
async def delete_brand(
    brand_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Brand).where(Brand.id == brand_id))
    brand = result.scalar_one_or_none()
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    await db.delete(brand)
