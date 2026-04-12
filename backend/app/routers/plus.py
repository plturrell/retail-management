from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.inventory import PLU, SKU
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.inventory import PLUCreate, PLURead

router = APIRouter(prefix="/api/skus/{sku_id}/plus", tags=["plus"])


@router.get("", response_model=PaginatedResponse[PLURead])
async def list_plus(
    sku_id: UUID,
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    base = select(PLU).where(PLU.sku_id == sku_id)
    count_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = count_result.scalar() or 0

    query = base.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    plus = result.scalars().all()

    return PaginatedResponse(
        data=[PLURead.model_validate(p) for p in plus],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=DataResponse[PLURead], status_code=201)
async def create_plu(
    sku_id: UUID,
    payload: PLUCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify SKU exists
    sku_result = await db.execute(select(SKU).where(SKU.id == sku_id))
    if sku_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="SKU not found")

    data = payload.model_dump()
    data["sku_id"] = sku_id
    plu = PLU(**data)
    db.add(plu)
    await db.flush()
    await db.refresh(plu)
    return DataResponse(data=PLURead.model_validate(plu))


@router.delete("/{plu_id}", status_code=204)
async def delete_plu(
    sku_id: UUID,
    plu_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PLU).where(PLU.id == plu_id, PLU.sku_id == sku_id)
    )
    plu = result.scalar_one_or_none()
    if plu is None:
        raise HTTPException(status_code=404, detail="PLU not found")
    await db.delete(plu)
