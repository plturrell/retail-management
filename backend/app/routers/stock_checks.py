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
from app.auth.dependencies import RoleEnum, get_current_user, require_store_access, require_store_role
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.inventory import (
    InventoryType,
    StockCheckCreate,
    StockCheckItemCreate,
    StockCheckItemRead,
    StockCheckRead,
    StockCheckStatus,
    StockCheckUpdate,
)
from app.services.supply_chain import list_stage_inventory

router = APIRouter(prefix="/api/stores/{store_id}/stock-checks", tags=["stock-checks"])


def _checks_col(store_id: UUID) -> str:
    return f"stores/{store_id}/stock_checks"


def _items_col(store_id: UUID, check_id: UUID) -> str:
    return f"stores/{store_id}/stock_checks/{check_id}/items"


def _inv_col(store_id: UUID) -> str:
    return f"stores/{store_id}/inventory"


def _to_check_read(data: dict) -> StockCheckRead:
    return StockCheckRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        check_date=data.get("check_date"),
        store_location=data.get("store_location"),
        notes=data.get("notes"),
        status=StockCheckStatus(data.get("status", StockCheckStatus.in_progress.value)),
        store_id=UUID(data["store_id"]) if isinstance(data.get("store_id"), str) else data.get("store_id"),
        total_items=data.get("total_items", 0),
        total_quantity=data.get("total_quantity", 0),
        created_by=UUID(data["created_by"]) if isinstance(data.get("created_by"), str) else data.get("created_by"),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
        updated_at=data.get("updated_at"),
    )


def _to_item_read(data: dict) -> StockCheckItemRead:
    expected = data.get("expected_qty")
    checked = data.get("checked_qty", 0)
    variance = (checked - expected) if expected is not None else None
    return StockCheckItemRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        stock_check_id=UUID(data["stock_check_id"]) if isinstance(data.get("stock_check_id"), str) else data.get("stock_check_id"),
        sku_id=UUID(data["sku_id"]) if isinstance(data.get("sku_id"), str) else data.get("sku_id") if data.get("sku_id") else None,
        product_code=data.get("product_code"),
        product_name=data.get("product_name", ""),
        checked_qty=checked,
        expected_qty=expected,
        unit_price=data.get("unit_price"),
        location=data.get("location"),
        condition=data.get("condition"),
        notes=data.get("notes"),
        variance=variance,
        created_at=data.get("created_at", datetime.now(timezone.utc)),
    )


# ── Stock Check CRUD ─────────────────────────────────────────────────────────

@router.get("", response_model=PaginatedResponse[StockCheckRead])
async def list_stock_checks(
    store_id: UUID,
    page: int = 1,
    page_size: int = 20,
    _: dict = Depends(require_store_access),
    db: FirestoreClient = Depends(get_firestore_db),
):
    all_items = query_collection(_checks_col(store_id), order_by="-check_date")
    total = len(all_items)
    offset = (page - 1) * page_size
    page_items = all_items[offset : offset + page_size]
    return PaginatedResponse(
        data=[_to_check_read(c) for c in page_items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{check_id}", response_model=DataResponse[StockCheckRead])
async def get_stock_check(
    store_id: UUID,
    check_id: UUID,
    _: dict = Depends(require_store_access),
    db: FirestoreClient = Depends(get_firestore_db),
):
    data = get_document(_checks_col(store_id), str(check_id))
    if data is None:
        raise HTTPException(status_code=404, detail="Stock check not found")
    return DataResponse(data=_to_check_read(data))


@router.post("", response_model=DataResponse[StockCheckRead], status_code=201)
async def create_stock_check(
    store_id: UUID,
    payload: StockCheckCreate,
    _: dict = Depends(require_store_role(RoleEnum.manager)),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    now = datetime.now(timezone.utc)
    doc_id = str(_uuid.uuid4())
    doc_data = payload.model_dump()
    doc_data["id"] = doc_id
    doc_data["store_id"] = str(store_id)
    doc_data["status"] = str(doc_data.get("status", StockCheckStatus.in_progress.value))
    doc_data["check_date"] = str(doc_data["check_date"])
    doc_data["total_items"] = 0
    doc_data["total_quantity"] = 0
    doc_data["created_by"] = str(user.get("id"))
    doc_data["created_at"] = now
    doc_data["updated_at"] = now

    created = create_document(_checks_col(store_id), doc_data, doc_id=doc_id)
    return DataResponse(data=_to_check_read(created))


@router.patch("/{check_id}", response_model=DataResponse[StockCheckRead])
async def update_stock_check(
    store_id: UUID,
    check_id: UUID,
    payload: StockCheckUpdate,
    _: dict = Depends(require_store_role(RoleEnum.manager)),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    col = _checks_col(store_id)
    existing = get_document(col, str(check_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Stock check not found")

    updates = payload.model_dump(exclude_unset=True)
    if "status" in updates:
        updates["status"] = str(updates["status"])
    if "check_date" in updates:
        updates["check_date"] = str(updates["check_date"])
    updates["updated_at"] = datetime.now(timezone.utc)
    updated = update_document(col, str(check_id), updates)
    return DataResponse(data=_to_check_read(updated))


@router.delete("/{check_id}", status_code=204)
async def delete_stock_check(
    store_id: UUID,
    check_id: UUID,
    _: dict = Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    col = _checks_col(store_id)
    existing = get_document(col, str(check_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Stock check not found")
    delete_document(col, str(check_id))


# ── Stock Check Items ─────────────────────────────────────────────────────────

@router.get("/{check_id}/items", response_model=PaginatedResponse[StockCheckItemRead])
async def list_stock_check_items(
    store_id: UUID,
    check_id: UUID,
    page: int = 1,
    page_size: int = 50,
    _: dict = Depends(require_store_access),
    db: FirestoreClient = Depends(get_firestore_db),
):
    # Verify stock check exists
    check = get_document(_checks_col(store_id), str(check_id))
    if check is None:
        raise HTTPException(status_code=404, detail="Stock check not found")

    all_items = query_collection(_items_col(store_id, check_id), order_by="product_name")
    total = len(all_items)
    offset = (page - 1) * page_size
    page_items = all_items[offset : offset + page_size]
    return PaginatedResponse(
        data=[_to_item_read(i) for i in page_items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/{check_id}/items", response_model=DataResponse[StockCheckItemRead], status_code=201)
async def add_stock_check_item(
    store_id: UUID,
    check_id: UUID,
    payload: StockCheckItemCreate,
    _: dict = Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    # Verify stock check exists
    check_col = _checks_col(store_id)
    check = get_document(check_col, str(check_id))
    if check is None:
        raise HTTPException(status_code=404, detail="Stock check not found")

    now = datetime.now(timezone.utc)
    doc_id = str(_uuid.uuid4())
    doc_data = payload.model_dump()
    doc_data["id"] = doc_id
    doc_data["stock_check_id"] = str(check_id)
    if doc_data.get("sku_id"):
        doc_data["sku_id"] = str(doc_data["sku_id"])

    # Look up expected quantity from the finished-stage ledger if sku_id provided
    if payload.sku_id:
        stage_items = list_stage_inventory(
            store_id,
            inventory_type=InventoryType.finished,
            sku_id=payload.sku_id,
        )
        if stage_items:
            doc_data["expected_qty"] = stage_items[0].quantity_on_hand

    doc_data["created_at"] = now

    created = create_document(_items_col(store_id, check_id), doc_data, doc_id=doc_id)

    # Update totals on parent stock check
    update_document(check_col, str(check_id), {
        "total_items": check.get("total_items", 0) + 1,
        "total_quantity": check.get("total_quantity", 0) + (payload.checked_qty or 0),
        "updated_at": now,
    })

    return DataResponse(data=_to_item_read(created))


# ── Reconciliation ────────────────────────────────────────────────────────────

@router.get("/{check_id}/reconciliation")
async def get_reconciliation(
    store_id: UUID,
    check_id: UUID,
    _: dict = Depends(require_store_access),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Compare checked quantities against expected inventory levels."""
    check = get_document(_checks_col(store_id), str(check_id))
    if check is None:
        raise HTTPException(status_code=404, detail="Stock check not found")

    items = query_collection(_items_col(store_id, check_id))

    total_checked = 0
    total_expected = 0
    variances: list[dict] = []
    matched = 0
    over = 0
    under = 0
    unmatched = 0

    for item in items:
        checked = item.get("checked_qty", 0)
        expected = item.get("expected_qty")
        total_checked += checked

        if expected is not None:
            total_expected += expected
            variance = checked - expected
            if variance == 0:
                matched += 1
            elif variance > 0:
                over += 1
            else:
                under += 1
            variances.append({
                "product_name": item.get("product_name", ""),
                "product_code": item.get("product_code", ""),
                "checked_qty": checked,
                "expected_qty": expected,
                "variance": variance,
                "status": "match" if variance == 0 else ("over" if variance > 0 else "under"),
            })
        else:
            unmatched += 1
            variances.append({
                "product_name": item.get("product_name", ""),
                "product_code": item.get("product_code", ""),
                "checked_qty": checked,
                "expected_qty": None,
                "variance": None,
                "status": "no_expected",
            })

    # Sort variances: biggest discrepancies first
    variances.sort(key=lambda v: abs(v["variance"]) if v["variance"] is not None else 0, reverse=True)

    return {
        "stock_check_id": str(check_id),
        "check_date": check.get("check_date"),
        "store_location": check.get("store_location"),
        "summary": {
            "total_items": len(items),
            "total_checked_qty": total_checked,
            "total_expected_qty": total_expected,
            "net_variance": total_checked - total_expected,
            "matched": matched,
            "over": over,
            "under": under,
            "unmatched": unmatched,
        },
        "items": variances,
    }
