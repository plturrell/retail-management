from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from google.cloud.firestore_v1.client import Client as FirestoreClient

from app.firestore import get_firestore_db
from app.firestore_helpers import (
    create_document,
    delete_document,
    get_document,
    query_collection,
    update_document,
)
from app.auth.dependencies import get_current_user
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.inventory import PromotionCreate, PromotionRead, PromotionUpdate

router = APIRouter(prefix="/api/promotions", tags=["promotions"])

PROMOTIONS_COL = "promotions"


def _to_read(data: dict) -> PromotionRead:
    return PromotionRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        disc_id=data.get("disc_id", ""),
        sku_id=UUID(data["sku_id"]) if data.get("sku_id") else None,
        category_id=UUID(data["category_id"]) if data.get("category_id") else None,
        line_type=data.get("line_type", ""),
        disc_method=data.get("disc_method", ""),
        disc_value=data.get("disc_value", 0),
        line_group=data.get("line_group"),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
        updated_at=data.get("updated_at"),
    )


@router.get("", response_model=PaginatedResponse[PromotionRead])
async def list_promotions(
    page: int = 1,
    page_size: int = 50,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    all_items = query_collection(PROMOTIONS_COL)
    total = len(all_items)
    offset = (page - 1) * page_size
    page_items = all_items[offset : offset + page_size]

    return PaginatedResponse(
        data=[_to_read(p) for p in page_items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=DataResponse[PromotionRead], status_code=201)
async def create_promotion(
    payload: PromotionCreate,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    now = datetime.now(timezone.utc)
    doc_id = str(_uuid.uuid4())
    doc_data = payload.model_dump()
    # Convert UUID fields to strings
    for k in ("sku_id", "category_id"):
        if doc_data.get(k) is not None:
            doc_data[k] = str(doc_data[k])
    doc_data["created_at"] = now
    doc_data["updated_at"] = now

    created = create_document(PROMOTIONS_COL, doc_data, doc_id=doc_id)
    return DataResponse(data=_to_read(created))


@router.patch("/{promotion_id}", response_model=DataResponse[PromotionRead])
async def update_promotion(
    promotion_id: UUID,
    payload: PromotionUpdate,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    existing = get_document(PROMOTIONS_COL, str(promotion_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Promotion not found")

    updates = payload.model_dump(exclude_unset=True)
    if updates:
        updates["updated_at"] = datetime.now(timezone.utc)
        updated = update_document(PROMOTIONS_COL, str(promotion_id), updates)
    else:
        updated = existing
    return DataResponse(data=_to_read(updated))


@router.delete("/{promotion_id}", status_code=204)
async def delete_promotion(
    promotion_id: UUID,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    existing = get_document(PROMOTIONS_COL, str(promotion_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Promotion not found")
    delete_document(PROMOTIONS_COL, str(promotion_id))
