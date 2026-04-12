from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.inventory import PLU, Inventory, Price, SKU
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.schemas.common import DataResponse
from app.schemas.inventory import SKURead, PriceRead, InventoryRead

router = APIRouter(prefix="/api/barcode", tags=["barcode"])


class BarcodeLookupResponse(BaseModel):
    sku: SKURead
    current_price: PriceRead | None = None
    stock: list[InventoryRead] = []

    model_config = {"from_attributes": True}


@router.get("/{plu_code}", response_model=DataResponse[BarcodeLookupResponse])
async def barcode_lookup(
    plu_code: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Find PLU
    result = await db.execute(select(PLU).where(PLU.plu_code == plu_code))
    plu = result.scalar_one_or_none()
    if plu is None:
        raise HTTPException(status_code=404, detail="Barcode not found")

    # Get SKU
    sku_result = await db.execute(select(SKU).where(SKU.id == plu.sku_id))
    sku = sku_result.scalar_one_or_none()
    if sku is None:
        raise HTTPException(status_code=404, detail="SKU not found for barcode")

    # Get current price (valid today)
    today = date.today()
    price_result = await db.execute(
        select(Price)
        .where(
            Price.sku_id == sku.id,
            Price.valid_from <= today,
            Price.valid_to >= today,
        )
        .order_by(Price.valid_from.desc())
        .limit(1)
    )
    current_price = price_result.scalar_one_or_none()

    # Get stock levels
    inv_result = await db.execute(
        select(Inventory).where(Inventory.sku_id == sku.id)
    )
    stock = inv_result.scalars().all()

    return DataResponse(
        data=BarcodeLookupResponse(
            sku=SKURead.model_validate(sku),
            current_price=PriceRead.model_validate(current_price) if current_price else None,
            stock=[InventoryRead.model_validate(i) for i in stock],
        )
    )
