from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from google.cloud.firestore_v1.client import Client as FirestoreClient

from app.firestore import get_firestore_db
from app.firestore_helpers import get_document, query_collection
from app.auth.dependencies import can_view_sensitive_operations, get_current_user
from app.schemas.common import DataResponse
from app.schemas.inventory import SKURead, PriceRead, InventoryRead

router = APIRouter(prefix="/api/barcode", tags=["barcode"])


class BarcodeLookupResponse(BaseModel):
    sku: SKURead
    current_price: PriceRead | None = None
    stock: list[InventoryRead] = []

    model_config = {"from_attributes": True}


def _redact_sensitive_sku_fields(data: dict) -> dict:
    redacted = dict(data)
    for field in ("cost_price", "supplier_name", "supplier_sku_code", "internal_code"):
        redacted[field] = None
    return redacted


@router.get("/{plu_code}", response_model=DataResponse[BarcodeLookupResponse])
async def barcode_lookup(
    plu_code: str,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    can_view_sensitive = any(
        can_view_sensitive_operations(role.get("role"))
        for role in user.get("store_roles", [])
    )

    # Find PLU
    plus = query_collection("plus", filters=[("plu_code", "==", plu_code)], limit=1)
    if not plus:
        raise HTTPException(status_code=404, detail="Barcode not found")
    plu = plus[0]

    # Get SKU
    sku_id = plu.get("sku_id", "")
    sku = get_document("skus", sku_id)
    if sku is None:
        raise HTTPException(status_code=404, detail="SKU not found for barcode")
    if not can_view_sensitive:
        sku = _redact_sensitive_sku_fields(sku)

    # Get current price (valid today)
    today = date.today().isoformat()
    prices = query_collection(
        "prices",
        filters=[
            ("sku_id", "==", sku_id),
            ("valid_from", "<=", today),
            ("valid_to", ">=", today),
        ],
        order_by="-valid_from",
        limit=1,
    )
    current_price = prices[0] if prices else None

    # Get stock levels
    stock = query_collection("inventory", filters=[("sku_id", "==", sku_id)])

    return DataResponse(
        data=BarcodeLookupResponse(
            sku=SKURead(**sku),
            current_price=PriceRead(**current_price) if current_price else None,
            stock=[InventoryRead(**i) for i in stock],
        )
    )
