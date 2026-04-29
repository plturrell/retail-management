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
from app.schemas.inventory import CategoryCreate, CategoryRead, CategoryUpdate

router = APIRouter(prefix="/api/stores/{store_id}/categories", tags=["categories"])


def _col(store_id: UUID) -> str:
    return f"stores/{store_id}/categories"


def _to_read(data: dict) -> CategoryRead:
    return CategoryRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        catg_code=data.get("catg_code", ""),
        cag_catg_code=data.get("cag_catg_code"),
        description=data.get("description", ""),
        parent_id=UUID(data["parent_id"]) if data.get("parent_id") else None,
        store_id=UUID(data["store_id"]) if isinstance(data.get("store_id"), str) else data.get("store_id"),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
        updated_at=data.get("updated_at"),
    )


@router.get("", response_model=PaginatedResponse[CategoryRead])
async def list_categories(
    store_id: UUID,
    page: int = 1,
    page_size: int = 100,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    all_items = query_collection(_col(store_id), order_by="catg_code")
    total = len(all_items)
    offset = (page - 1) * page_size
    page_items = all_items[offset : offset + page_size]

    return PaginatedResponse(
        data=[_to_read(c) for c in page_items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{category_id}", response_model=DataResponse[CategoryRead])
async def get_category(
    store_id: UUID,
    category_id: UUID,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    data = get_document(_col(store_id), str(category_id))
    if data is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return DataResponse(data=_to_read(data))


@router.post("", response_model=DataResponse[CategoryRead], status_code=201)
async def create_category(
    store_id: UUID,
    payload: CategoryCreate,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    now = datetime.now(timezone.utc)
    doc_id = str(_uuid.uuid4())
    doc_data = payload.model_dump()
    doc_data["store_id"] = str(store_id)
    # Convert UUID fields to strings for Firestore
    for k in ("parent_id",):
        if doc_data.get(k) is not None:
            doc_data[k] = str(doc_data[k])
    doc_data["created_at"] = now
    doc_data["updated_at"] = now

    created = create_document(_col(store_id), doc_data, doc_id=doc_id)
    return DataResponse(data=_to_read(created))


@router.patch("/{category_id}", response_model=DataResponse[CategoryRead])
async def update_category(
    store_id: UUID,
    category_id: UUID,
    payload: CategoryUpdate,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    col = _col(store_id)
    existing = get_document(col, str(category_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Category not found")

    updates = payload.model_dump(exclude_unset=True)
    if updates:
        for k in ("parent_id",):
            if k in updates and updates[k] is not None:
                updates[k] = str(updates[k])
        updates["updated_at"] = datetime.now(timezone.utc)
        updated = update_document(col, str(category_id), updates)
    else:
        updated = existing
    return DataResponse(data=_to_read(updated))


@router.delete("/{category_id}", status_code=204)
async def delete_category(
    store_id: UUID,
    category_id: UUID,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    col = _col(store_id)
    existing = get_document(col, str(category_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Category not found")
    delete_document(col, str(category_id))
