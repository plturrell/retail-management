from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from google.cloud.firestore_v1.client import Client as FirestoreClient

from app.firestore import get_firestore_db
from app.firestore_helpers import (
    create_document,
    get_document,
    query_collection,
    update_document,
)
from app.auth.dependencies import RoleEnum, require_store_role
from app.schemas.banking import (
    BankTransactionRead,
    BankTransactionReconcile,
    BankTransactionUpdate,
    OCBCImportResult,
    WebhookResult,
)
from app.schemas.common import DataResponse, PaginatedResponse
from app.services.ocbc_parser import parse_ocbc_csv
from app.services.hipay import parse_hipay_webhook
from app.services.airwallex import parse_airwallex_webhook

router = APIRouter(
    prefix="/api/stores/{store_id}/banking",
    tags=["banking"],
)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def _banking_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/banking"


def _txn_to_read(data: dict) -> BankTransactionRead:
    """Convert a Firestore bank transaction dict to BankTransactionRead."""
    txn_date = data.get("transaction_date")
    if isinstance(txn_date, str):
        txn_date = date.fromisoformat(txn_date)
    return BankTransactionRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        store_id=UUID(data["store_id"]) if isinstance(data.get("store_id"), str) else data.get("store_id"),
        source=data.get("source", ""),
        transaction_date=txn_date,
        description=data.get("description", ""),
        reference=data.get("reference"),
        amount=data.get("amount", 0),
        balance=data.get("balance"),
        category=data.get("category"),
        account_id=UUID(data["account_id"]) if data.get("account_id") else None,
        journal_entry_id=UUID(data["journal_entry_id"]) if data.get("journal_entry_id") else None,
        is_reconciled=data.get("is_reconciled", False),
        raw_data=data.get("raw_data"),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
        updated_at=data.get("updated_at"),
    )


# ---- Duplicate check helper ----

def _check_duplicate(store_id: UUID, source: str, reference: str, txn_date, amount: float) -> bool:
    """Return True if a duplicate transaction exists."""
    txn_date_str = txn_date.isoformat() if isinstance(txn_date, date) else str(txn_date)
    existing = query_collection(
        _banking_collection(store_id),
        filters=[
            ("source", "==", source),
            ("reference", "==", reference),
            ("transaction_date", "==", txn_date_str),
            ("amount", "==", amount),
        ],
        limit=1,
    )
    return len(existing) > 0


def _create_txn(store_id: UUID, txn_data) -> dict:
    """Create a bank transaction document from parsed data."""
    now = datetime.now(timezone.utc)
    doc_id = str(_uuid.uuid4())
    txn_date = txn_data.transaction_date
    doc = {
        "store_id": str(store_id),
        "source": txn_data.source,
        "transaction_date": txn_date.isoformat() if isinstance(txn_date, date) else str(txn_date),
        "description": txn_data.description,
        "reference": txn_data.reference,
        "amount": txn_data.amount,
        "balance": txn_data.balance,
        "category": txn_data.category,
        "raw_data": txn_data.raw_data,
        "is_reconciled": False,
        "account_id": None,
        "journal_entry_id": None,
        "created_at": now,
        "updated_at": now,
    }
    return create_document(_banking_collection(store_id), doc, doc_id=doc_id)


# ---- OCBC CSV Import ----

@router.post("/import/ocbc", response_model=DataResponse[OCBCImportResult])
async def import_ocbc_csv(
    store_id: UUID,
    file: UploadFile = File(...),
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Upload an OCBC CSV statement and import bank transactions."""
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10MB limit")

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

    try:
        parsed = parse_ocbc_csv(text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    imported = 0
    skipped = 0
    errors: list[str] = []

    for txn_data in parsed:
        if _check_duplicate(store_id, txn_data.source, txn_data.reference, txn_data.transaction_date, txn_data.amount):
            skipped += 1
            continue
        try:
            _create_txn(store_id, txn_data)
            imported += 1
        except Exception as e:
            errors.append(f"Row {txn_data.reference}: {str(e)}")

    return DataResponse(data=OCBCImportResult(
        imported=imported, skipped=skipped, errors=errors
    ))


# ---- HiPay Webhook ----

@router.post("/webhook/hipay", response_model=DataResponse[WebhookResult])
async def hipay_webhook(
    store_id: UUID,
    payload: dict,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Receive a HiPay webhook notification and create a bank transaction."""
    try:
        txn_data = parse_hipay_webhook(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid HiPay payload: {e}")

    if _check_duplicate(store_id, txn_data.source, txn_data.reference, txn_data.transaction_date, txn_data.amount):
        return DataResponse(data=WebhookResult(success=True, message="Duplicate transaction, skipped"))

    created = _create_txn(store_id, txn_data)
    return DataResponse(data=WebhookResult(
        success=True, transaction_id=UUID(created["id"]), message="Transaction created"
    ))


# ---- Airwallex Webhook ----

@router.post("/webhook/airwallex", response_model=DataResponse[WebhookResult])
async def airwallex_webhook(
    store_id: UUID,
    payload: dict,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Receive an Airwallex webhook notification and create a bank transaction."""
    try:
        txn_data = parse_airwallex_webhook(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid Airwallex payload: {e}")

    if _check_duplicate(store_id, txn_data.source, txn_data.reference, txn_data.transaction_date, txn_data.amount):
        return DataResponse(data=WebhookResult(success=True, message="Duplicate transaction, skipped"))

    created = _create_txn(store_id, txn_data)
    return DataResponse(data=WebhookResult(
        success=True, transaction_id=UUID(created["id"]), message="Transaction created"
    ))


# ---- List / Get / Update / Reconcile ----

@router.get("/transactions", response_model=PaginatedResponse[BankTransactionRead])
async def list_transactions(
    store_id: UUID,
    source: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    is_reconciled: Optional[bool] = None,
    category: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """List bank transactions with optional filters."""
    filters = []
    if source is not None:
        filters.append(("source", "==", source))
    if is_reconciled is not None:
        filters.append(("is_reconciled", "==", is_reconciled))
    if category is not None:
        filters.append(("category", "==", category))
    if date_from is not None:
        filters.append(("transaction_date", ">=", date_from.isoformat()))
    if date_to is not None:
        filters.append(("transaction_date", "<=", date_to.isoformat()))

    all_items = query_collection(_banking_collection(store_id), filters=filters, order_by="-transaction_date")
    total = len(all_items)
    offset = (page - 1) * page_size
    page_items = all_items[offset:offset + page_size]

    return PaginatedResponse(
        data=[_txn_to_read(i) for i in page_items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/transactions/{txn_id}", response_model=DataResponse[BankTransactionRead])
async def get_transaction(
    store_id: UUID,
    txn_id: UUID,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Get a single bank transaction by ID."""
    txn = get_document(_banking_collection(store_id), str(txn_id))
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return DataResponse(data=_txn_to_read(txn))


@router.patch("/transactions/{txn_id}", response_model=DataResponse[BankTransactionRead])
async def update_transaction(
    store_id: UUID,
    txn_id: UUID,
    payload: BankTransactionUpdate,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Update a bank transaction's category or account link."""
    txn = get_document(_banking_collection(store_id), str(txn_id))
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    updates = payload.model_dump(exclude_unset=True)
    if "account_id" in updates and updates["account_id"] is not None:
        updates["account_id"] = str(updates["account_id"])
    if updates:
        updates["updated_at"] = datetime.now(timezone.utc)
        txn = update_document(_banking_collection(store_id), str(txn_id), updates)
    return DataResponse(data=_txn_to_read(txn))


@router.post(
    "/transactions/{txn_id}/reconcile",
    response_model=DataResponse[BankTransactionRead],
)
async def reconcile_transaction(
    store_id: UUID,
    txn_id: UUID,
    payload: BankTransactionReconcile,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Mark a bank transaction as reconciled."""
    txn = get_document(_banking_collection(store_id), str(txn_id))
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if txn.get("is_reconciled"):
        raise HTTPException(status_code=400, detail="Transaction already reconciled")

    updates = {"is_reconciled": True, "updated_at": datetime.now(timezone.utc)}
    if payload.account_id is not None:
        updates["account_id"] = str(payload.account_id)

    txn = update_document(_banking_collection(store_id), str(txn_id), updates)
    return DataResponse(data=_txn_to_read(txn))
