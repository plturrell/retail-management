from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.store import Store
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.store import StoreCreate, StoreRead, StoreUpdate

router = APIRouter(prefix="/api/stores", tags=["stores"])


@router.get("", response_model=PaginatedResponse[StoreRead])
async def list_stores(
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    store_ids = [ur.store_id for ur in user.store_roles]
    query = select(Store).where(Store.id.in_(store_ids))
    total_result = await db.execute(
        select(Store.id).where(Store.id.in_(store_ids))
    )
    total = len(total_result.all())

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    stores = result.scalars().all()

    return PaginatedResponse(
        data=[StoreRead.model_validate(s) for s in stores],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{store_id}", response_model=DataResponse[StoreRead])
async def get_store(
    store_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")
    return DataResponse(data=StoreRead.model_validate(store))


@router.post("", response_model=DataResponse[StoreRead], status_code=201)
async def create_store(
    payload: StoreCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    store = Store(**payload.model_dump())
    db.add(store)
    await db.flush()
    await db.refresh(store)
    return DataResponse(data=StoreRead.model_validate(store))


@router.patch("/{store_id}", response_model=DataResponse[StoreRead])
async def update_store(
    store_id: UUID,
    payload: StoreUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(store, key, value)

    await db.flush()
    await db.refresh(store)
    return DataResponse(data=StoreRead.model_validate(store))


@router.delete("/{store_id}", status_code=204)
async def delete_store(
    store_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")
    await db.delete(store)
