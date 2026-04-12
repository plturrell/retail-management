from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.inventory import Promotion
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.inventory import PromotionCreate, PromotionRead, PromotionUpdate

router = APIRouter(prefix="/api/promotions", tags=["promotions"])


@router.get("", response_model=PaginatedResponse[PromotionRead])
async def list_promotions(
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    count_result = await db.execute(select(Promotion.id))
    total = len(count_result.all())

    query = select(Promotion).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    promos = result.scalars().all()

    return PaginatedResponse(
        data=[PromotionRead.model_validate(p) for p in promos],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=DataResponse[PromotionRead], status_code=201)
async def create_promotion(
    payload: PromotionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    promo = Promotion(**payload.model_dump())
    db.add(promo)
    await db.flush()
    await db.refresh(promo)
    return DataResponse(data=PromotionRead.model_validate(promo))


@router.patch("/{promotion_id}", response_model=DataResponse[PromotionRead])
async def update_promotion(
    promotion_id: UUID,
    payload: PromotionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Promotion).where(Promotion.id == promotion_id))
    promo = result.scalar_one_or_none()
    if promo is None:
        raise HTTPException(status_code=404, detail="Promotion not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(promo, key, value)

    await db.flush()
    await db.refresh(promo)
    return DataResponse(data=PromotionRead.model_validate(promo))


@router.delete("/{promotion_id}", status_code=204)
async def delete_promotion(
    promotion_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Promotion).where(Promotion.id == promotion_id))
    promo = result.scalar_one_or_none()
    if promo is None:
        raise HTTPException(status_code=404, detail="Promotion not found")
    await db.delete(promo)
