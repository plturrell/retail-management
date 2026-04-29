from __future__ import annotations

import csv
import io
import uuid as _uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
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
from app.schemas.inventory import InventoryCreate, InventoryRead, InventoryType, InventoryUpdate
from app.services.inventory_ledger import record_movement as record_ledger_movement
from app.services.manager_copilot import adjustment_collection
from app.services.supply_chain import (
    SupplyActionSource,
    adjust_stage_inventory,
    ensure_finished_stage_inventory,
)

router = APIRouter(prefix="/api/stores/{store_id}/inventory", tags=["inventory"])


class InventoryAdjustment(BaseModel):
    quantity: int = Field(..., description="Positive to add, negative to subtract")
    reason: str = Field(..., max_length=500)
    source: str = Field("manual", max_length=64)
    note: str | None = Field(None, max_length=1000)
    recommendation_id: UUID | None = None


def _inv_col(store_id: UUID) -> str:
    return f"stores/{store_id}/stock"


def _sku_col(store_id: UUID) -> str:
    return f"stores/{store_id}/inventory"


def _to_read(data: dict) -> InventoryRead:
    return InventoryRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        sku_id=UUID(data["sku_id"]) if isinstance(data.get("sku_id"), str) else data.get("sku_id"),
        store_id=UUID(data["store_id"]) if isinstance(data.get("store_id"), str) else data.get("store_id"),
        qty_on_hand=data.get("qty_on_hand", 0),
        reorder_level=data.get("reorder_level", 0),
        reorder_qty=data.get("reorder_qty", 0),
        serial_number=data.get("serial_number"),
        last_updated=data.get("last_updated", datetime.now(timezone.utc)),
        source=data.get("source"),
        created_by=UUID(data["created_by"]) if isinstance(data.get("created_by"), str) else data.get("created_by"),
        updated_by=UUID(data["updated_by"]) if isinstance(data.get("updated_by"), str) else data.get("updated_by"),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
        updated_at=data.get("updated_at"),
    )


def _actor_uuid(user: dict) -> UUID:
    return UUID(str(user.get("id")))


@router.get("", response_model=PaginatedResponse[InventoryRead])
async def list_inventory(
    store_id: UUID,
    page: int = 1,
    page_size: int = 50,
    low_stock: bool = False,
    _=Depends(require_store_access),
    db: FirestoreClient = Depends(get_firestore_db),
):
    all_items = query_collection(_inv_col(store_id))

    if low_stock:
        all_items = [
            i for i in all_items
            if i.get("qty_on_hand", 0) <= i.get("reorder_level", 0)
        ]

    total = len(all_items)
    offset = (page - 1) * page_size
    page_items = all_items[offset : offset + page_size]

    return PaginatedResponse(
        data=[_to_read(i) for i in page_items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/alerts", response_model=DataResponse[list[InventoryRead]])
async def inventory_alerts(
    store_id: UUID,
    _=Depends(require_store_access),
    db: FirestoreClient = Depends(get_firestore_db),
):
    all_items = query_collection(_inv_col(store_id))
    low = [
        i for i in all_items
        if i.get("qty_on_hand", 0) <= i.get("reorder_level", 0)
    ]
    return DataResponse(data=[_to_read(i) for i in low])


@router.get("/sku/{sku_id}", response_model=DataResponse[InventoryRead])
async def get_inventory_by_sku(
    store_id: UUID,
    sku_id: UUID,
    _=Depends(require_store_access),
    db: FirestoreClient = Depends(get_firestore_db),
):
    items = query_collection(
        _inv_col(store_id),
        filters=[("sku_id", "==", str(sku_id))],
        limit=1,
    )
    if not items:
        raise HTTPException(status_code=404, detail="Inventory record not found")
    return DataResponse(data=_to_read(items[0]))


@router.post("", response_model=DataResponse[InventoryRead], status_code=201)
async def create_inventory(
    store_id: UUID,
    payload: InventoryCreate,
    _=Depends(require_store_role(RoleEnum.manager)),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    if payload.store_id != store_id:
        raise HTTPException(status_code=400, detail="Payload store_id must match route store_id")

    # Verify SKU exists
    sku = get_document(_sku_col(store_id), str(payload.sku_id))
    if sku is None:
        raise HTTPException(status_code=400, detail="SKU is not available in this store")

    now = datetime.now(timezone.utc)
    doc_id = str(_uuid.uuid4())
    doc_data = payload.model_dump()
    user_id = str(user.get("id"))
    doc_data["id"] = doc_id
    doc_data["store_id"] = str(store_id)
    doc_data["sku_id"] = str(doc_data["sku_id"])
    doc_data["last_updated"] = now
    doc_data["source"] = "manual"
    doc_data["created_by"] = user_id
    doc_data["updated_by"] = user_id
    doc_data["created_at"] = now
    doc_data["updated_at"] = now

    created = create_document(_inv_col(store_id), doc_data, doc_id=doc_id)
    adjust_stage_inventory(
        store_id,
        payload.sku_id,
        InventoryType.finished,
        _actor_uuid(user),
        delta_qty=payload.qty_on_hand,
        source=SupplyActionSource.manual,
        reference_type="inventory_seed",
        reference_id=UUID(doc_id),
    )
    return DataResponse(data=_to_read(get_document(_inv_col(store_id), doc_id) or created))


@router.patch("/{inventory_id}", response_model=DataResponse[InventoryRead])
async def update_inventory(
    store_id: UUID,
    inventory_id: UUID,
    payload: InventoryUpdate,
    _=Depends(require_store_role(RoleEnum.manager)),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    col = _inv_col(store_id)
    existing = get_document(col, str(inventory_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Inventory record not found")

    updates = payload.model_dump(exclude_unset=True)
    now = datetime.now(timezone.utc)
    actor_user_id = _actor_uuid(user)
    if payload.qty_on_hand is not None:
        stage = ensure_finished_stage_inventory(
            store_id,
            UUID(str(existing.get("sku_id"))),
            actor_user_id,
            source=SupplyActionSource.system,
        )
        current_qty = stage.quantity_on_hand if stage is not None else 0
        adjust_stage_inventory(
            store_id,
            UUID(str(existing.get("sku_id"))),
            InventoryType.finished,
            actor_user_id,
            delta_qty=payload.qty_on_hand - current_qty,
            source=SupplyActionSource.manual,
            reference_type="inventory_set",
            reference_id=inventory_id,
        )
        updates.pop("qty_on_hand", None)
    updates["last_updated"] = now
    updates["source"] = "manual"
    updates["updated_by"] = str(user.get("id"))
    updates["updated_at"] = now
    updated = update_document(col, str(inventory_id), updates)
    return DataResponse(data=_to_read(updated))


@router.post("/{inventory_id}/adjust", response_model=DataResponse[InventoryRead])
async def adjust_inventory(
    store_id: UUID,
    inventory_id: UUID,
    payload: InventoryAdjustment,
    _=Depends(require_store_role(RoleEnum.manager)),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    col = _inv_col(store_id)
    existing = get_document(col, str(inventory_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Inventory record not found")

    actor_user_id = _actor_uuid(user)
    stage = ensure_finished_stage_inventory(
        store_id,
        UUID(str(existing.get("sku_id"))),
        actor_user_id,
        source=SupplyActionSource.system,
    )
    current_qty = stage.quantity_on_hand if stage is not None else 0
    new_qty = current_qty + payload.quantity
    if new_qty < 0:
        raise HTTPException(
            status_code=400,
            detail=f"Adjustment would result in negative stock ({new_qty})",
        )

    now = datetime.now(timezone.utc)
    user_id = str(user.get("id"))
    adjust_stage_inventory(
        store_id,
        UUID(str(existing.get("sku_id"))),
        InventoryType.finished,
        actor_user_id,
        delta_qty=payload.quantity,
        source=SupplyActionSource(payload.source),
        reference_type="inventory_adjustment",
        reference_id=inventory_id,
    )
    updated = update_document(col, str(inventory_id), {
        "last_updated": now,
        "source": payload.source,
        "updated_by": user_id,
        "updated_at": now,
    })
    adjustment_id = str(_uuid.uuid4())
    create_document(
        adjustment_collection(store_id),
        {
            "id": adjustment_id,
            "inventory_id": str(inventory_id),
            "sku_id": str(existing.get("sku_id")),
            "store_id": str(store_id),
            "quantity_delta": payload.quantity,
            "resulting_qty": new_qty,
            "reason": payload.reason,
            "source": payload.source,
            "created_by": user_id,
            "recommendation_id": str(payload.recommendation_id) if payload.recommendation_id else None,
            "note": payload.note,
            "created_at": now,
        },
        doc_id=adjustment_id,
    )
    # Dual-write to the TiDB ledger; safe no-op if SQL layer is disabled.
    await record_ledger_movement(
        store_id=store_id,
        sku_id=existing.get("sku_id"),
        delta_qty=payload.quantity,
        resulting_qty=new_qty,
        source=payload.source,
        reference_type="inventory_adjustment",
        reference_id=inventory_id,
        reason=payload.reason,
        actor_user_id=user_id,
        event_time=now,
    )
    return DataResponse(data=_to_read(updated))


class CSVImportResult(BaseModel):
    imported: int = Field(0, description="Number of new inventory records created")
    updated: int = Field(0, description="Number of existing inventory records updated")
    skipped: int = Field(0, description="Rows skipped due to missing data or unknown SKUs")
    errors: list[str] = Field(default_factory=list)


_REQUIRED_CSV_COLUMNS = {"sku_code", "qty_on_hand"}
_OPTIONAL_CSV_COLUMNS = {"reorder_level", "reorder_qty"}
_MAX_CSV_BYTES = 5 * 1024 * 1024  # 5 MB
_MAX_CSV_ROWS = 5_000


def _parse_int_field(row: dict, key: str, default: int = 0) -> int:
    raw = (row.get(key) or "").strip()
    if not raw:
        return default
    return int(raw)


@router.post("/import-csv", response_model=CSVImportResult)
async def import_inventory_csv(
    store_id: UUID,
    file: UploadFile = File(...),
    _=Depends(require_store_role(RoleEnum.manager)),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Import / update inventory rows from a CSV file.

    Required columns: ``sku_code``, ``qty_on_hand``.
    Optional columns: ``reorder_level``, ``reorder_qty``.

    For each row:
    - if a SKU with the given ``sku_code`` exists in the store, the matching
      stock record is created (when missing) or updated, with stage-inventory
      adjusted by the delta;
    - rows referencing unknown SKUs are skipped and reported in ``errors``.
    """
    raw = await file.read(_MAX_CSV_BYTES + 1)
    if len(raw) > _MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV file exceeds 5MB limit")
    if not raw:
        raise HTTPException(status_code=400, detail="CSV file is empty")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HTTPException(status_code=400, detail="CSV is missing a header row")
    headers = {h.strip().lower() for h in reader.fieldnames}
    missing = _REQUIRED_CSV_COLUMNS - headers
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"CSV is missing required column(s): {sorted(missing)}",
        )

    actor_uuid = _actor_uuid(user)
    user_id = str(actor_uuid)
    inv_col = _inv_col(store_id)
    sku_col = _sku_col(store_id)
    now = datetime.now(timezone.utc)

    imported = 0
    updated = 0
    skipped = 0
    errors: list[str] = []

    for index, row in enumerate(reader, start=2):  # header is line 1
        if index - 1 > _MAX_CSV_ROWS:
            errors.append(f"Row {index}: file exceeds {_MAX_CSV_ROWS}-row limit, remaining rows skipped")
            break

        # Normalise header casing.
        row = {(k or "").strip().lower(): v for k, v in row.items()}
        sku_code = (row.get("sku_code") or "").strip()
        if not sku_code:
            skipped += 1
            errors.append(f"Row {index}: missing sku_code")
            continue

        try:
            qty_on_hand = _parse_int_field(row, "qty_on_hand")
            reorder_level = _parse_int_field(row, "reorder_level")
            reorder_qty = _parse_int_field(row, "reorder_qty")
        except ValueError:
            skipped += 1
            errors.append(f"Row {index} (sku={sku_code}): non-integer numeric value")
            continue

        if qty_on_hand < 0 or reorder_level < 0 or reorder_qty < 0:
            skipped += 1
            errors.append(f"Row {index} (sku={sku_code}): negative quantity")
            continue

        skus = query_collection(
            sku_col,
            filters=[("sku_code", "==", sku_code)],
            limit=1,
        )
        if not skus:
            skipped += 1
            errors.append(f"Row {index}: SKU '{sku_code}' not found in store")
            continue
        sku_record = skus[0]
        sku_id_str = str(sku_record.get("id"))
        sku_uuid = UUID(sku_id_str)

        existing_records = query_collection(
            inv_col,
            filters=[("sku_id", "==", sku_id_str)],
            limit=1,
        )

        # Source of truth for `qty_on_hand` is the *stage* ledger; the stock
        # record is kept in sync by `adjust_stage_inventory -> _sync_finished_stock`.
        # We therefore compute the delta against the current stage quantity,
        # not the (potentially stale) stock.qty_on_hand, and let the stage
        # pipeline propagate the new value into the stock record.
        stage = ensure_finished_stage_inventory(
            store_id,
            sku_uuid,
            actor_uuid,
            source=SupplyActionSource.system,
        )
        current_stage_qty = stage.quantity_on_hand if stage is not None else 0
        delta_qty = qty_on_hand - current_stage_qty

        if existing_records:
            existing = existing_records[0]
            existing_id = str(existing.get("id"))
            # Update *only* the fields the stage pipeline doesn't own.
            update_document(inv_col, existing_id, {
                "reorder_level": reorder_level,
                "reorder_qty": reorder_qty,
                "last_updated": now,
                "updated_by": user_id,
                "updated_at": now,
            })
            adjust_stage_inventory(
                store_id,
                sku_uuid,
                InventoryType.finished,
                actor_uuid,
                delta_qty=delta_qty,
                source=SupplyActionSource.manual,
                reference_type="inventory_csv_update",
                reference_id=UUID(existing_id),
            )
            await record_ledger_movement(
                store_id=store_id,
                sku_id=sku_uuid,
                delta_qty=delta_qty,
                resulting_qty=qty_on_hand,
                source="csv_import",
                reference_type="inventory_csv_update",
                reference_id=existing_id,
                actor_user_id=user_id,
                event_time=now,
            )
            updated += 1
        else:
            # Create a minimal stock row; qty_on_hand is populated via the
            # stage adjustment that follows.
            doc_id = str(_uuid.uuid4())
            create_document(inv_col, {
                "id": doc_id,
                "store_id": str(store_id),
                "sku_id": sku_id_str,
                "qty_on_hand": 0,
                "reorder_level": reorder_level,
                "reorder_qty": reorder_qty,
                "last_updated": now,
                "source": "csv_import",
                "created_by": user_id,
                "updated_by": user_id,
                "created_at": now,
                "updated_at": now,
            }, doc_id=doc_id)
            adjust_stage_inventory(
                store_id,
                sku_uuid,
                InventoryType.finished,
                actor_uuid,
                delta_qty=delta_qty,
                source=SupplyActionSource.manual,
                reference_type="inventory_csv_create",
                reference_id=UUID(doc_id),
            )
            await record_ledger_movement(
                store_id=store_id,
                sku_id=sku_uuid,
                delta_qty=delta_qty,
                resulting_qty=qty_on_hand,
                source="csv_import",
                reference_type="inventory_csv_create",
                reference_id=doc_id,
                actor_user_id=user_id,
                event_time=now,
            )
            imported += 1

    return CSVImportResult(
        imported=imported,
        updated=updated,
        skipped=skipped,
        errors=errors,
    )


@router.delete("/{inventory_id}", status_code=204)
async def delete_inventory(
    store_id: UUID,
    inventory_id: UUID,
    _=Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    col = _inv_col(store_id)
    existing = get_document(col, str(inventory_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Inventory record not found")
    delete_document(col, str(inventory_id))


@router.get("/multica/analyze", response_model=dict)
async def analyze_anomalies_multica(
    store_id: UUID,
    low_stock_threshold: int = 5,
    _=Depends(require_store_access),
):
    """Hits the SPCS Multica agent natively inside Snowflake."""
    from app.services.multica_client import analyze_inventory_health
    resp = await analyze_inventory_health(str(store_id), low_stock_threshold)
    return resp.model_dump()
