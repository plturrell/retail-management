from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.inventory import Category
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.inventory import CategoryCreate, CategoryRead, CategoryUpdate

router = APIRouter(prefix="/api/stores/{store_id}/categories", tags=["categories"])


@router.get("", response_model=PaginatedResponse[CategoryRead])
async def list_categories(
    store_id: UUID,
    page: int = 1,
    page_size: int = 100,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    base = select(Category).where(Category.store_id == store_id)
    count_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = count_result.scalar() or 0

    query = base.order_by(Category.catg_code).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    categories = result.scalars().all()

    return PaginatedResponse(
        data=[CategoryRead.model_validate(c) for c in categories],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{category_id}", response_model=DataResponse[CategoryRead])
async def get_category(
    store_id: UUID,
    category_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Category).where(Category.id == category_id, Category.store_id == store_id)
    )
    category = result.scalar_one_or_none()
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return DataResponse(data=CategoryRead.model_validate(category))


@router.post("", response_model=DataResponse[CategoryRead], status_code=201)
async def create_category(
    store_id: UUID,
    payload: CategoryCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = payload.model_dump()
    data["store_id"] = store_id
    category = Category(**data)
    db.add(category)
    await db.flush()
    await db.refresh(category)
    return DataResponse(data=CategoryRead.model_validate(category))


@router.patch("/{category_id}", response_model=DataResponse[CategoryRead])
async def update_category(
    store_id: UUID,
    category_id: UUID,
    payload: CategoryUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Category).where(Category.id == category_id, Category.store_id == store_id)
    )
    category = result.scalar_one_or_none()
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(category, key, value)

    await db.flush()
    await db.refresh(category)
    return DataResponse(data=CategoryRead.model_validate(category))


@router.delete("/{category_id}", status_code=204)
async def delete_category(
    store_id: UUID,
    category_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Category).where(Category.id == category_id, Category.store_id == store_id)
    )
    category = result.scalar_one_or_none()
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    await db.delete(category)
