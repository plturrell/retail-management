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
from app.schemas.inventory import BrandCreate, BrandRead, BrandUpdate

router = APIRouter(prefix="/api/brands", tags=["brands"])

BRANDS_COL = "brands"


def _to_read(data: dict) -> BrandRead:
    return BrandRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        name=data.get("name", ""),
        category_type=data.get("category_type"),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
    )


@router.get("", response_model=PaginatedResponse[BrandRead])
async def list_brands(
    page: int = 1,
    page_size: int = 100,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    all_items = query_collection(BRANDS_COL, order_by="name")
    total = len(all_items)
    offset = (page - 1) * page_size
    page_items = all_items[offset : offset + page_size]

    return PaginatedResponse(
        data=[_to_read(b) for b in page_items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{brand_id}", response_model=DataResponse[BrandRead])
async def get_brand(
    brand_id: UUID,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    data = get_document(BRANDS_COL, str(brand_id))
    if data is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    return DataResponse(data=_to_read(data))


@router.post("", response_model=DataResponse[BrandRead], status_code=201)
async def create_brand(
    payload: BrandCreate,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    now = datetime.now(timezone.utc)
    doc_id = str(_uuid.uuid4())
    doc_data = payload.model_dump()
    doc_data["created_at"] = now
    doc_data["updated_at"] = now

    created = create_document(BRANDS_COL, doc_data, doc_id=doc_id)
    return DataResponse(data=_to_read(created))


@router.patch("/{brand_id}", response_model=DataResponse[BrandRead])
async def update_brand(
    brand_id: UUID,
    payload: BrandUpdate,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    existing = get_document(BRANDS_COL, str(brand_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    updates = payload.model_dump(exclude_unset=True)
    if updates:
        updates["updated_at"] = datetime.now(timezone.utc)
        updated = update_document(BRANDS_COL, str(brand_id), updates)
    else:
        updated = existing
    return DataResponse(data=_to_read(updated))


@router.delete("/{brand_id}", status_code=204)
async def delete_brand(
    brand_id: UUID,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    existing = get_document(BRANDS_COL, str(brand_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    delete_document(BRANDS_COL, str(brand_id))
