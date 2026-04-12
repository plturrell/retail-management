from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.inventory import Inventory, SKU
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.inventory import InventoryCreate, InventoryRead, InventoryUpdate

router = APIRouter(prefix="/api/stores/{store_id}/inventory", tags=["inventory"])


class InventoryAdjustment(BaseModel):
    quantity: int = Field(..., description="Positive to add, negative to subtract")
    reason: str = Field(..., max_length=500)


@router.get("", response_model=PaginatedResponse[InventoryRead])
async def list_inventory(
    store_id: UUID,
    page: int = 1,
    page_size: int = 50,
    low_stock: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    base = select(Inventory).where(Inventory.store_id == store_id)
    if low_stock:
        base = base.where(Inventory.qty_on_hand <= Inventory.reorder_level)

    count_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = count_result.scalar() or 0

    query = base.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()

    return PaginatedResponse(
        data=[InventoryRead.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/alerts", response_model=DataResponse[list[InventoryRead]])
async def inventory_alerts(
    store_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Inventory).where(
        Inventory.store_id == store_id,
        Inventory.qty_on_hand <= Inventory.reorder_level,
    )
    result = await db.execute(query)
    items = result.scalars().all()
    return DataResponse(data=[InventoryRead.model_validate(i) for i in items])


@router.get("/sku/{sku_id}", response_model=DataResponse[InventoryRead])
async def get_inventory_by_sku(
    store_id: UUID,
    sku_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Inventory).where(
            Inventory.sku_id == sku_id, Inventory.store_id == store_id
        )
    )
    inv = result.scalar_one_or_none()
    if inv is None:
        raise HTTPException(status_code=404, detail="Inventory record not found")
    return DataResponse(data=InventoryRead.model_validate(inv))


@router.post("", response_model=DataResponse[InventoryRead], status_code=201)
async def create_inventory(
    store_id: UUID,
    payload: InventoryCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = payload.model_dump()
    data["store_id"] = store_id
    data["last_updated"] = datetime.now(UTC)
    inv = Inventory(**data)
    db.add(inv)
    await db.flush()
    await db.refresh(inv)
    return DataResponse(data=InventoryRead.model_validate(inv))


@router.patch("/{inventory_id}", response_model=DataResponse[InventoryRead])
async def update_inventory(
    store_id: UUID,
    inventory_id: UUID,
    payload: InventoryUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Inventory).where(Inventory.id == inventory_id, Inventory.store_id == store_id)
    )
    inv = result.scalar_one_or_none()
    if inv is None:
        raise HTTPException(status_code=404, detail="Inventory record not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(inv, key, value)
    inv.last_updated = datetime.now(UTC)

    await db.flush()
    await db.refresh(inv)
    return DataResponse(data=InventoryRead.model_validate(inv))


@router.post("/{inventory_id}/adjust", response_model=DataResponse[InventoryRead])
async def adjust_inventory(
    store_id: UUID,
    inventory_id: UUID,
    payload: InventoryAdjustment,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Inventory).where(Inventory.id == inventory_id, Inventory.store_id == store_id)
    )
    inv = result.scalar_one_or_none()
    if inv is None:
        raise HTTPException(status_code=404, detail="Inventory record not found")

    new_qty = inv.qty_on_hand + payload.quantity
    if new_qty < 0:
        raise HTTPException(
            status_code=400,
            detail=f"Adjustment would result in negative stock ({new_qty})",
        )

    inv.qty_on_hand = new_qty
    inv.last_updated = datetime.now(UTC)

    await db.flush()
    await db.refresh(inv)
    return DataResponse(data=InventoryRead.model_validate(inv))


@router.delete("/{inventory_id}", status_code=204)
async def delete_inventory(
    store_id: UUID,
    inventory_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Inventory).where(Inventory.id == inventory_id, Inventory.store_id == store_id)
    )
    inv = result.scalar_one_or_none()
    if inv is None:
        raise HTTPException(status_code=404, detail="Inventory record not found")
    await db.delete(inv)
