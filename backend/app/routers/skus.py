from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from google.cloud.firestore_v1.client import Client as FirestoreClient

from app.firestore import get_firestore_db
from app.firestore_helpers import (
    create_document,
    delete_document,
    get_document,
    query_collection,
    update_document,
)
from app.auth.dependencies import (
    RoleEnum,
    can_view_sensitive_operations,
    get_current_user,
    require_store_access,
    require_store_role,
)
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.inventory import (
    InventoryType,
    SKUCreate,
    SKURead,
    SKUUpdate,
    SourcingStrategy,
)

router = APIRouter(prefix="/api/stores/{store_id}/skus", tags=["skus"])


def _col(store_id: UUID) -> str:
    return f"stores/{store_id}/inventory"


def _to_read(data: dict) -> SKURead:
    return SKURead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        sku_code=data.get("sku_code", ""),
        description=data.get("description", ""),
        long_description=data.get("long_description"),
        cost_price=data.get("cost_price"),
        category_id=UUID(data["category_id"]) if data.get("category_id") else None,
        brand_id=UUID(data["brand_id"]) if data.get("brand_id") else None,
        tax_code=data.get("tax_code", "G"),
        gender=data.get("gender"),
        age_group=data.get("age_group"),
        is_unique_piece=data.get("is_unique_piece", False),
        use_stock=data.get("use_stock", True),
        block_sales=data.get("block_sales", False),
        inventory_type=InventoryType(data.get("inventory_type", InventoryType.finished.value)),
        sourcing_strategy=SourcingStrategy(
            data.get("sourcing_strategy", SourcingStrategy.supplier_premade.value)
        ),
        supplier_name=data.get("supplier_name"),
        supplier_sku_code=data.get("supplier_sku_code"),
        store_id=UUID(data["store_id"]) if isinstance(data.get("store_id"), str) else data.get("store_id"),
        source=data.get("source"),
        created_by=UUID(data["created_by"]) if isinstance(data.get("created_by"), str) else data.get("created_by"),
        updated_by=UUID(data["updated_by"]) if isinstance(data.get("updated_by"), str) else data.get("updated_by"),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
        updated_at=data.get("updated_at"),
    )


def _redact_sensitive_sku_fields(data: dict) -> dict:
    redacted = dict(data)
    for field in ("cost_price", "supplier_name", "supplier_sku_code", "internal_code"):
        redacted[field] = None
    return redacted


def _serialize_enum_value(value):
    return value.value if hasattr(value, "value") else str(value)


@router.get("", response_model=PaginatedResponse[SKURead])
async def list_skus(
    store_id: UUID,
    page: int = 1,
    page_size: int = 50,
    search: str | None = Query(None, description="Search by SKU code or description"),
    category_id: UUID | None = None,
    brand_id: UUID | None = None,
    role_assignment: dict = Depends(require_store_access),
    db: FirestoreClient = Depends(get_firestore_db),
):
    filters = []
    if category_id:
        filters.append(("category_id", "==", str(category_id)))
    if brand_id:
        filters.append(("brand_id", "==", str(brand_id)))

    all_items = query_collection(_col(store_id), filters=filters, order_by="sku_code")

    # Client-side search (Firestore doesn't support ILIKE)
    if search:
        search_lower = search.lower()
        all_items = [
            item for item in all_items
            if search_lower in item.get("sku_code", "").lower()
            or search_lower in item.get("description", "").lower()
        ]

    total = len(all_items)
    offset = (page - 1) * page_size
    page_items = all_items[offset : offset + page_size]

    show_sensitive_fields = can_view_sensitive_operations(role_assignment.get("role"))
    return PaginatedResponse(
        data=[
            _to_read(item if show_sensitive_fields else _redact_sensitive_sku_fields(item))
            for item in page_items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{sku_id}", response_model=DataResponse[SKURead])
async def get_sku(
    store_id: UUID,
    sku_id: UUID,
    role_assignment: dict = Depends(require_store_access),
    db: FirestoreClient = Depends(get_firestore_db),
):
    data = get_document(_col(store_id), str(sku_id))
    if data is None:
        raise HTTPException(status_code=404, detail="SKU not found")
    if not can_view_sensitive_operations(role_assignment.get("role")):
        data = _redact_sensitive_sku_fields(data)
    return DataResponse(data=_to_read(data))


@router.post("", response_model=DataResponse[SKURead], status_code=201)
async def create_sku(
    store_id: UUID,
    payload: SKUCreate,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    now = datetime.now(timezone.utc)
    doc_id = str(_uuid.uuid4())
    doc_data = payload.model_dump()
    user_id = str(user.get("id"))
    doc_data["id"] = doc_id
    doc_data["store_id"] = str(store_id)
    # Convert UUID fields to strings
    for k in ("category_id", "brand_id"):
        if doc_data.get(k) is not None:
            doc_data[k] = str(doc_data[k])
    for k in ("inventory_type", "sourcing_strategy"):
        if doc_data.get(k) is not None:
            doc_data[k] = _serialize_enum_value(doc_data[k])
    doc_data["source"] = "manual"
    doc_data["created_by"] = user_id
    doc_data["updated_by"] = user_id
    doc_data["created_at"] = now
    doc_data["updated_at"] = now

    created = create_document(_col(store_id), doc_data, doc_id=doc_id)
    return DataResponse(data=_to_read(created))


@router.patch("/{sku_id}", response_model=DataResponse[SKURead])
async def update_sku(
    store_id: UUID,
    sku_id: UUID,
    payload: SKUUpdate,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    col = _col(store_id)
    existing = get_document(col, str(sku_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="SKU not found")

    updates = payload.model_dump(exclude_unset=True)
    if updates:
        for k in ("category_id", "brand_id"):
            if k in updates and updates[k] is not None:
                updates[k] = str(updates[k])
        for k in ("inventory_type", "sourcing_strategy"):
            if k in updates and updates[k] is not None:
                updates[k] = _serialize_enum_value(updates[k])
        updates["source"] = "manual"
        updates["updated_by"] = str(user.get("id"))
        updates["updated_at"] = datetime.now(timezone.utc)
        updated = update_document(col, str(sku_id), updates)
    else:
        updated = existing
    return DataResponse(data=_to_read(updated))


@router.delete("/{sku_id}", status_code=204)
async def delete_sku(
    store_id: UUID,
    sku_id: UUID,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    col = _col(store_id)
    existing = get_document(col, str(sku_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="SKU not found")
    delete_document(col, str(sku_id))
