from __future__ import annotations

from datetime import date, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import and_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.banking import BankTransaction
from app.models.user import UserStoreRole
from app.auth.dependencies import require_store_access, require_store_role
from app.models.user import RoleEnum
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


# ---- OCBC CSV Import ----

@router.post("/import/ocbc", response_model=DataResponse[OCBCImportResult])
async def import_ocbc_csv(
    store_id: UUID,
    file: UploadFile = File(...),
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    """Upload an OCBC CSV statement and import bank transactions.

    Duplicate transactions (same source+reference+date+amount) are skipped.
    """
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
        # Check for duplicate
        existing = await db.execute(
            select(BankTransaction).where(
                and_(
                    BankTransaction.source == txn_data.source,
                    BankTransaction.reference == txn_data.reference,
                    BankTransaction.transaction_date == txn_data.transaction_date,
                    BankTransaction.amount == txn_data.amount,
                )
            )
        )
        if existing.scalar_one_or_none() is not None:
            skipped += 1
            continue

        try:
            txn = BankTransaction(
                store_id=store_id,
                source=txn_data.source,
                transaction_date=txn_data.transaction_date,
                description=txn_data.description,
                reference=txn_data.reference,
                amount=txn_data.amount,
                balance=txn_data.balance,
                category=txn_data.category,
                raw_data=txn_data.raw_data,
            )
            db.add(txn)
            await db.flush()
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
    _: UserStoreRole = Depends(require_store_access),
    db: AsyncSession = Depends(get_db),
):
    """Receive a HiPay webhook notification and create a bank transaction."""
    try:
        txn_data = parse_hipay_webhook(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid HiPay payload: {e}")

    # Check for duplicate
    existing = await db.execute(
        select(BankTransaction).where(
            and_(
                BankTransaction.source == txn_data.source,
                BankTransaction.reference == txn_data.reference,
                BankTransaction.transaction_date == txn_data.transaction_date,
                BankTransaction.amount == txn_data.amount,
            )
        )
    )
    if existing.scalar_one_or_none() is not None:
        return DataResponse(data=WebhookResult(
            success=True, message="Duplicate transaction, skipped"
        ))

    txn = BankTransaction(
        store_id=store_id,
        source=txn_data.source,
        transaction_date=txn_data.transaction_date,
        description=txn_data.description,
        reference=txn_data.reference,
        amount=txn_data.amount,
        balance=txn_data.balance,
        category=txn_data.category,
        raw_data=txn_data.raw_data,
    )
    db.add(txn)
    await db.flush()
    await db.refresh(txn)

    return DataResponse(data=WebhookResult(
        success=True, transaction_id=txn.id, message="Transaction created"
    ))


# ---- Airwallex Webhook ----

@router.post("/webhook/airwallex", response_model=DataResponse[WebhookResult])
async def airwallex_webhook(
    store_id: UUID,
    payload: dict,
    _: UserStoreRole = Depends(require_store_access),
    db: AsyncSession = Depends(get_db),
):
    """Receive an Airwallex webhook notification and create a bank transaction."""
    try:
        txn_data = parse_airwallex_webhook(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid Airwallex payload: {e}")

    # Check for duplicate
    existing = await db.execute(
        select(BankTransaction).where(
            and_(
                BankTransaction.source == txn_data.source,
                BankTransaction.reference == txn_data.reference,
                BankTransaction.transaction_date == txn_data.transaction_date,
                BankTransaction.amount == txn_data.amount,
            )
        )
    )
    if existing.scalar_one_or_none() is not None:
        return DataResponse(data=WebhookResult(
            success=True, message="Duplicate transaction, skipped"
        ))

    txn = BankTransaction(
        store_id=store_id,
        source=txn_data.source,
        transaction_date=txn_data.transaction_date,
        description=txn_data.description,
        reference=txn_data.reference,
        amount=txn_data.amount,
        balance=txn_data.balance,
        category=txn_data.category,
        raw_data=txn_data.raw_data,
    )
    db.add(txn)
    await db.flush()
    await db.refresh(txn)

    return DataResponse(data=WebhookResult(
        success=True, transaction_id=txn.id, message="Transaction created"
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
    _: UserStoreRole = Depends(require_store_access),
    db: AsyncSession = Depends(get_db),
):
    """List bank transactions with optional filters."""
    base = select(BankTransaction).where(BankTransaction.store_id == store_id)

    if source is not None:
        base = base.where(BankTransaction.source == source)
    if date_from is not None:
        base = base.where(BankTransaction.transaction_date >= date_from)
    if date_to is not None:
        base = base.where(BankTransaction.transaction_date <= date_to)
    if is_reconciled is not None:
        base = base.where(BankTransaction.is_reconciled == is_reconciled)
    if category is not None:
        base = base.where(BankTransaction.category == category)

    count_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = count_result.scalar() or 0

    query = base.order_by(BankTransaction.transaction_date.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()

    return PaginatedResponse(
        data=[BankTransactionRead.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/transactions/{txn_id}", response_model=DataResponse[BankTransactionRead])
async def get_transaction(
    store_id: UUID,
    txn_id: UUID,
    _: UserStoreRole = Depends(require_store_access),
    db: AsyncSession = Depends(get_db),
):
    """Get a single bank transaction by ID."""
    result = await db.execute(
        select(BankTransaction).where(
            BankTransaction.id == txn_id,
            BankTransaction.store_id == store_id,
        )
    )
    txn = result.scalar_one_or_none()
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return DataResponse(data=BankTransactionRead.model_validate(txn))


@router.patch("/transactions/{txn_id}", response_model=DataResponse[BankTransactionRead])
async def update_transaction(
    store_id: UUID,
    txn_id: UUID,
    payload: BankTransactionUpdate,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    """Update a bank transaction's category or account link."""
    result = await db.execute(
        select(BankTransaction).where(
            BankTransaction.id == txn_id,
            BankTransaction.store_id == store_id,
        )
    )
    txn = result.scalar_one_or_none()
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(txn, key, value)

    await db.flush()
    await db.refresh(txn)
    return DataResponse(data=BankTransactionRead.model_validate(txn))


@router.post(
    "/transactions/{txn_id}/reconcile",
    response_model=DataResponse[BankTransactionRead],
)
async def reconcile_transaction(
    store_id: UUID,
    txn_id: UUID,
    payload: BankTransactionReconcile,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    """Mark a bank transaction as reconciled.

    In a full implementation this would also create a journal entry
    linking to the chart of accounts. For now it sets is_reconciled=True
    and optionally links the account_id.
    """
    result = await db.execute(
        select(BankTransaction).where(
            BankTransaction.id == txn_id,
            BankTransaction.store_id == store_id,
        )
    )
    txn = result.scalar_one_or_none()
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if txn.is_reconciled:
        raise HTTPException(status_code=400, detail="Transaction already reconciled")

    txn.is_reconciled = True
    if payload.account_id is not None:
        txn.account_id = payload.account_id

    # TODO: Create JournalEntry + JournalLines when finance models exist
    # journal_entry = JournalEntry(...)
    # txn.journal_entry_id = journal_entry.id

    await db.flush()
    await db.refresh(txn)
    return DataResponse(data=BankTransactionRead.model_validate(txn))
