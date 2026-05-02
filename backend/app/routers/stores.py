import uuid as _uuid
from datetime import date, datetime, time, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from google.cloud.firestore_v1.client import Client as FirestoreClient

from app.firestore import get_firestore_db
from app.firestore_helpers import (
    create_document,
    delete_document,
    get_document,
    query_collection,
    update_document,
)
from app.auth.dependencies import get_current_user, is_system_admin
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.store import StoreCreate, StoreRead, StoreUpdate
from app.services.store_identity import canonical_active_location_stores

router = APIRouter(prefix="/api/stores", tags=["stores"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_time(val) -> time | None:
    """Coerce a stored value back to a datetime.time."""
    if val is None:
        return None
    if isinstance(val, time):
        return val
    if isinstance(val, str):
        return time.fromisoformat(val)
    return val


def _parse_date(val) -> date | None:
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        return date.fromisoformat(val)
    return val


def _store_to_read(data: dict) -> StoreRead:
    return StoreRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        store_code=data.get("store_code"),
        name=data.get("name", ""),
        location=data.get("location", ""),
        address=data.get("address", ""),
        business_hours_start=_parse_time(data.get("business_hours_start")) or time(10, 0),
        business_hours_end=_parse_time(data.get("business_hours_end")) or time(22, 0),
        store_type=data.get("store_type", "retail"),
        operational_status=data.get("operational_status", "active"),
        is_home_base=data.get("is_home_base", False),
        is_temp_warehouse=data.get("is_temp_warehouse", False),
        planned_open_date=_parse_date(data.get("planned_open_date")),
        notes=data.get("notes"),
        is_active=data.get("is_active", True),
        nec_tenant_code=data.get("nec_tenant_code"),
        nec_store_id=data.get("nec_store_id"),
        nec_taxable=data.get("nec_taxable", True),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
        updated_at=data.get("updated_at"),
    )


def _serialize_store_data(data: dict) -> dict:
    """Convert time objects to ISO strings for Firestore storage."""
    out = dict(data)
    for key in ("business_hours_start", "business_hours_end"):
        if key in out and isinstance(out[key], time):
            out[key] = out[key].isoformat()
    if "planned_open_date" in out and isinstance(out["planned_open_date"], date):
        out["planned_open_date"] = out["planned_open_date"].isoformat()
    return out


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=PaginatedResponse[StoreRead])
async def list_stores(
    page: int = 1,
    page_size: int = 50,
    active_locations: bool = Query(
        False,
        description="Return one preferred store document per canonical operating location.",
    ),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    if is_system_admin(user):
        all_stores = query_collection("stores")
    else:
        store_ids = {
            str(sr.get("store_id", "")).strip()
            for sr in user.get("store_roles", [])
            if str(sr.get("store_id", "")).strip()
        }
        if not store_ids:
            return PaginatedResponse(data=[], total=0, page=page, page_size=page_size)

        # Fetch each store doc individually (Firestore has no IN query for doc IDs)
        all_stores = []
        for sid in store_ids:
            doc = get_document("stores", sid)
            if doc is not None:
                all_stores.append(doc)

    if active_locations:
        location_stores = canonical_active_location_stores(all_stores)
        all_stores = location_stores or all_stores

    total = len(all_stores)
    start = (page - 1) * page_size
    page_items = all_stores[start : start + page_size]

    return PaginatedResponse(
        data=[_store_to_read(s) for s in page_items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{store_id}", response_model=DataResponse[StoreRead])
async def get_store(
    store_id: UUID,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    store = get_document("stores", str(store_id))
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")
    return DataResponse(data=_store_to_read(store))


@router.post("", response_model=DataResponse[StoreRead], status_code=201)
async def create_store(
    payload: StoreCreate,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    store_id = str(_uuid.uuid4())
    now = datetime.now(timezone.utc)
    doc_data = _serialize_store_data(payload.model_dump())
    doc_data["created_at"] = now
    doc_data["updated_at"] = now

    created = create_document("stores", doc_data, doc_id=store_id)
    return DataResponse(data=_store_to_read(created))


@router.patch("/{store_id}", response_model=DataResponse[StoreRead])
async def update_store(
    store_id: UUID,
    payload: StoreUpdate,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    existing = get_document("stores", str(store_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Store not found")

    updates = _serialize_store_data(payload.model_dump(exclude_unset=True))
    if updates:
        updates["updated_at"] = datetime.now(timezone.utc)
        updated = update_document("stores", str(store_id), updates)
    else:
        updated = existing
    return DataResponse(data=_store_to_read(updated))


@router.delete("/{store_id}", status_code=204)
async def delete_store(
    store_id: UUID,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    existing = get_document("stores", str(store_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Store not found")
    delete_document("stores", str(store_id))
