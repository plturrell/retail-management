from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime, timezone
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
from app.auth.dependencies import RoleEnum, get_current_user, require_store_access, require_store_role
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.inventory import PriceCreate, PriceRead, PriceUpdate

router = APIRouter(prefix="/api/stores/{store_id}/prices", tags=["prices"])


def _col(store_id: UUID) -> str:
    return f"stores/{store_id}/prices"


def _to_read(data: dict) -> PriceRead:
    def _parse_date(v):
        if isinstance(v, date):
            return v
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, str):
            return date.fromisoformat(v)
        return v

    return PriceRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        sku_id=UUID(data["sku_id"]) if isinstance(data.get("sku_id"), str) else data.get("sku_id"),
        store_id=UUID(data["store_id"]) if isinstance(data.get("store_id"), str) else data.get("store_id"),
        price_incl_tax=data.get("price_incl_tax", 0),
        price_excl_tax=data.get("price_excl_tax", 0),
        price_unit=data.get("price_unit", 1),
        valid_from=_parse_date(data.get("valid_from")),
        valid_to=_parse_date(data.get("valid_to")),
        source=data.get("source"),
        created_by=UUID(data["created_by"]) if isinstance(data.get("created_by"), str) else data.get("created_by"),
        updated_by=UUID(data["updated_by"]) if isinstance(data.get("updated_by"), str) else data.get("updated_by"),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
        updated_at=data.get("updated_at"),
    )


@router.get("", response_model=PaginatedResponse[PriceRead])
async def list_prices(
    store_id: UUID,
    sku_id: UUID | None = None,
    page: int = 1,
    page_size: int = 50,
    _: dict = Depends(require_store_access),
    db: FirestoreClient = Depends(get_firestore_db),
):
    filters = []
    if sku_id:
        filters.append(("sku_id", "==", str(sku_id)))

    all_items = query_collection(_col(store_id), filters=filters)
    total = len(all_items)
    offset = (page - 1) * page_size
    page_items = all_items[offset : offset + page_size]

    return PaginatedResponse(
        data=[_to_read(p) for p in page_items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=DataResponse[PriceRead], status_code=201)
async def create_price(
    store_id: UUID,
    payload: PriceCreate,
    _: dict = Depends(require_store_role(RoleEnum.manager)),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    now = datetime.now(timezone.utc)
    doc_id = str(_uuid.uuid4())
    doc_data = payload.model_dump()
    user_id = str(user.get("id"))
    doc_data["id"] = doc_id
    doc_data["store_id"] = str(store_id)
    # Convert UUID fields
    if doc_data.get("sku_id") is not None:
        doc_data["sku_id"] = str(doc_data["sku_id"])
    # Convert date fields to isoformat strings for Firestore
    for k in ("valid_from", "valid_to"):
        if isinstance(doc_data.get(k), date):
            doc_data[k] = doc_data[k].isoformat()
    doc_data["source"] = "manual"
    doc_data["created_by"] = user_id
    doc_data["updated_by"] = user_id
    doc_data["created_at"] = now
    doc_data["updated_at"] = now

    created = create_document(_col(store_id), doc_data, doc_id=doc_id)
    return DataResponse(data=_to_read(created))


@router.patch("/{price_id}", response_model=DataResponse[PriceRead])
async def update_price(
    store_id: UUID,
    price_id: UUID,
    payload: PriceUpdate,
    _: dict = Depends(require_store_role(RoleEnum.manager)),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    col = _col(store_id)
    existing = get_document(col, str(price_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Price not found")

    updates = payload.model_dump(exclude_unset=True)
    if updates:
        for k in ("valid_from", "valid_to"):
            if isinstance(updates.get(k), date):
                updates[k] = updates[k].isoformat()
        updates["source"] = "manual"
        updates["updated_by"] = str(user.get("id"))
        updates["updated_at"] = datetime.now(timezone.utc)
        updated = update_document(col, str(price_id), updates)
    else:
        updated = existing
    return DataResponse(data=_to_read(updated))


@router.delete("/{price_id}", status_code=204)
async def delete_price(
    store_id: UUID,
    price_id: UUID,
    _: dict = Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    col = _col(store_id)
    existing = get_document(col, str(price_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Price not found")
    delete_document(col, str(price_id))
