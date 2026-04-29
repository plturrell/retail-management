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
)
from app.auth.dependencies import get_current_user
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.inventory import PLUCreate, PLURead

router = APIRouter(prefix="/api/skus/{sku_id}/plus", tags=["plus"])

PLUS_COL = "plus"


def _to_read(data: dict) -> PLURead:
    return PLURead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        plu_code=data.get("plu_code", ""),
        sku_id=UUID(data["sku_id"]) if isinstance(data.get("sku_id"), str) else data.get("sku_id"),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
    )


@router.get("", response_model=PaginatedResponse[PLURead])
async def list_plus(
    sku_id: UUID,
    page: int = 1,
    page_size: int = 50,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    all_items = query_collection(
        PLUS_COL,
        filters=[("sku_id", "==", str(sku_id))],
    )
    total = len(all_items)
    offset = (page - 1) * page_size
    page_items = all_items[offset : offset + page_size]

    return PaginatedResponse(
        data=[_to_read(p) for p in page_items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=DataResponse[PLURead], status_code=201)
async def create_plu(
    sku_id: UUID,
    payload: PLUCreate,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    # Verify SKU exists — search across all stores' inventory collections
    # PLUs are global; we just check any inventory doc with this sku_id exists
    # For simplicity, we trust the sku_id is valid (Firestore doesn't have FK constraints)

    now = datetime.now(timezone.utc)
    doc_id = str(_uuid.uuid4())
    doc_data = payload.model_dump()
    doc_data["sku_id"] = str(sku_id)
    doc_data["created_at"] = now

    created = create_document(PLUS_COL, doc_data, doc_id=doc_id)
    return DataResponse(data=_to_read(created))


@router.delete("/{plu_id}", status_code=204)
async def delete_plu(
    sku_id: UUID,
    plu_id: UUID,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    data = get_document(PLUS_COL, str(plu_id))
    if data is None or data.get("sku_id") != str(sku_id):
        raise HTTPException(status_code=404, detail="PLU not found")
    delete_document(PLUS_COL, str(plu_id))
