from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional
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
    batch_write,
)
from app.auth.dependencies import (
    RoleEnum,
    get_current_user,
    require_any_store_role,
    require_store_role,
)
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.finance import (
    AccountBalance,
    AccountCreate,
    AccountRead,
    AccountUpdate,
    JournalEntryCreate,
    JournalEntryRead,
    JournalLineRead,
    LedgerEntry,
)

router = APIRouter(tags=["finance"])

VALID_ACCOUNT_TYPES = {"asset", "liability", "equity", "revenue", "expense"}


# ---------- Helpers ----------

ACCOUNTS_COLLECTION = "accounts"


def _acct_to_read(data: dict) -> AccountRead:
    """Convert a Firestore account dict to AccountRead."""
    return AccountRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        code=data.get("code", ""),
        name=data.get("name", ""),
        account_type=data.get("account_type", ""),
        parent_id=UUID(data["parent_id"]) if data.get("parent_id") else None,
        description=data.get("description"),
        is_active=data.get("is_active", True),
        store_id=UUID(data["store_id"]) if data.get("store_id") else None,
        created_at=data.get("created_at", datetime.now(timezone.utc)),
        updated_at=data.get("updated_at", datetime.now(timezone.utc)),
    )


# ---------- Chart of Accounts ----------

@router.post("/api/accounts", response_model=DataResponse[AccountRead], status_code=201)
async def create_account(
    payload: AccountCreate,
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    if payload.account_type not in VALID_ACCOUNT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid account_type: {payload.account_type}. Must be one of: asset, liability, equity, revenue, expense",
        )

    # Check for duplicate code
    existing = query_collection(ACCOUNTS_COLLECTION, filters=[("code", "==", payload.code)], limit=1)
    if existing:
        raise HTTPException(status_code=409, detail=f"Account code '{payload.code}' already exists")

    now = datetime.now(timezone.utc)
    doc_id = str(_uuid.uuid4())
    doc_data = payload.model_dump()
    doc_data["store_id"] = str(payload.store_id) if payload.store_id else None
    doc_data["parent_id"] = str(payload.parent_id) if payload.parent_id else None
    doc_data["created_at"] = now
    doc_data["updated_at"] = now

    created = create_document(ACCOUNTS_COLLECTION, doc_data, doc_id=doc_id)
    return DataResponse(data=_acct_to_read(created))


@router.get("/api/accounts", response_model=DataResponse[list[AccountRead]])
async def list_accounts(
    account_type: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    filters = []
    if account_type:
        if account_type not in VALID_ACCOUNT_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid account_type: {account_type}")
        filters.append(("account_type", "==", account_type))
    if is_active is not None:
        filters.append(("is_active", "==", is_active))

    accounts = query_collection(ACCOUNTS_COLLECTION, filters=filters, order_by="code")
    return DataResponse(data=[_acct_to_read(a) for a in accounts])


@router.get("/api/accounts/{account_id}", response_model=DataResponse[AccountRead])
async def get_account(
    account_id: UUID,
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    account = get_document(ACCOUNTS_COLLECTION, str(account_id))
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return DataResponse(data=_acct_to_read(account))


@router.patch("/api/accounts/{account_id}", response_model=DataResponse[AccountRead])
async def update_account(
    account_id: UUID,
    payload: AccountUpdate,
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    account = get_document(ACCOUNTS_COLLECTION, str(account_id))
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    updates = payload.model_dump(exclude_unset=True)
    if "parent_id" in updates and updates["parent_id"] is not None:
        updates["parent_id"] = str(updates["parent_id"])
    if updates:
        updates["updated_at"] = datetime.now(timezone.utc)
        account = update_document(ACCOUNTS_COLLECTION, str(account_id), updates)
    return DataResponse(data=_acct_to_read(account))


DEFAULT_CHART_OF_ACCOUNTS = [
    # Assets (1xxx)
    ("1000", "Cash", "asset", None),
    ("1010", "OCBC Bank Account", "asset", None),
    ("1020", "HiPay Settlement", "asset", None),
    ("1030", "Airwallex Settlement", "asset", None),
    ("1100", "Accounts Receivable", "asset", None),
    ("1200", "Inventory Asset", "asset", None),
    ("1300", "Prepaid Expenses", "asset", None),
    # Liabilities (2xxx)
    ("2000", "Accounts Payable", "liability", None),
    ("2100", "CPF Payable", "liability", None),
    ("2200", "Salary Payable", "liability", None),
    ("2300", "Accrued Expenses", "liability", None),
    # Equity (3xxx)
    ("3000", "Owner's Equity", "equity", None),
    ("3100", "Retained Earnings", "equity", None),
    # Revenue (4xxx)
    ("4000", "Sales Revenue", "revenue", None),
    ("4010", "Sales - Jewellery", "revenue", "4000"),
    ("4020", "Sales - Homeware", "revenue", "4000"),
    ("4100", "Other Income", "revenue", None),
    # Expenses (5xxx)
    ("5000", "Cost of Goods Sold", "expense", None),
    ("5100", "Salary Expense", "expense", None),
    ("5110", "CPF Expense (Employer)", "expense", "5100"),
    ("5200", "Rent Expense", "expense", None),
    ("5300", "Utilities", "expense", None),
    ("5400", "Marketing", "expense", None),
    ("5500", "Bank Charges", "expense", None),
    ("5600", "Other Expenses", "expense", None),
]


@router.post("/api/accounts/seed", response_model=DataResponse[list[AccountRead]], status_code=201)
async def seed_chart_of_accounts(
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    # Check if accounts already seeded
    existing = query_collection(ACCOUNTS_COLLECTION, limit=1)
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Chart of accounts already seeded. Delete existing accounts first.",
        )

    now = datetime.now(timezone.utc)
    code_to_id: dict[str, str] = {}
    operations = []

    # First pass: create all accounts without parent links
    for code, name, acct_type, _parent_code in DEFAULT_CHART_OF_ACCOUNTS:
        doc_id = str(_uuid.uuid4())
        code_to_id[code] = doc_id
        operations.append({
            "action": "create",
            "collection": ACCOUNTS_COLLECTION,
            "doc_id": doc_id,
            "data": {
                "code": code,
                "name": name,
                "account_type": acct_type,
                "is_active": True,
                "parent_id": None,
                "description": None,
                "store_id": None,
                "created_at": now,
                "updated_at": now,
            },
        })

    # Set parent_id for sub-accounts
    for code, _name, _acct_type, parent_code in DEFAULT_CHART_OF_ACCOUNTS:
        if parent_code and parent_code in code_to_id:
            # Find the operation for this code and set parent_id
            for op in operations:
                if op["doc_id"] == code_to_id[code]:
                    op["data"]["parent_id"] = code_to_id[parent_code]
                    break

    batch_write(operations)

    # Return all created accounts
    accounts = query_collection(ACCOUNTS_COLLECTION, order_by="code")
    return DataResponse(data=[_acct_to_read(a) for a in accounts])


# ---------- Journal Entries ----------


def _je_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/finance/journal-entries"


def _generate_entry_number(store_id: UUID, entry_date: date) -> str:
    """Generate a unique entry number like JE-YYYYMMDD-001."""
    date_str = entry_date.strftime("%Y%m%d")
    prefix = f"JE-{date_str}-"
    existing = query_collection(
        _je_collection(store_id),
        filters=[("entry_number", ">=", prefix), ("entry_number", "<=", prefix + "\uf8ff")],
    )
    count = len(existing) + 1
    return f"{prefix}{count:03d}"


def _entry_dict_to_read(data: dict) -> JournalEntryRead:
    """Convert a Firestore journal entry dict to JournalEntryRead."""
    lines = []
    for line in data.get("lines", []):
        lines.append(JournalLineRead(
            id=UUID(line["id"]) if isinstance(line.get("id"), str) else line.get("id"),
            journal_entry_id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
            account_id=UUID(line["account_id"]) if isinstance(line.get("account_id"), str) else line.get("account_id"),
            debit=Decimal(str(line.get("debit", 0))),
            credit=Decimal(str(line.get("credit", 0))),
            description=line.get("description"),
            account_name=None,
            created_at=line.get("created_at", data.get("created_at", datetime.now(timezone.utc))),
        ))

    entry_date = data.get("entry_date")
    if isinstance(entry_date, str):
        entry_date = date.fromisoformat(entry_date)

    return JournalEntryRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        entry_number=data.get("entry_number", ""),
        entry_date=entry_date,
        description=data.get("description", ""),
        store_id=UUID(data["store_id"]) if isinstance(data.get("store_id"), str) else data.get("store_id"),
        source_type=data.get("source_type", "manual"),
        source_ref=data.get("source_ref"),
        is_posted=data.get("is_posted", False),
        posted_by=UUID(data["posted_by"]) if data.get("posted_by") else None,
        created_by=UUID(data["created_by"]) if isinstance(data.get("created_by"), str) else data.get("created_by"),
        lines=lines,
        created_at=data.get("created_at", datetime.now(timezone.utc)),
        updated_at=data.get("updated_at", datetime.now(timezone.utc)),
    )


@router.post(
    "/api/stores/{store_id}/journal-entries",
    response_model=DataResponse[JournalEntryRead],
    status_code=201,
)
async def create_journal_entry(
    store_id: UUID,
    payload: JournalEntryCreate,
    role: dict = Depends(require_store_role(RoleEnum.owner)),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    total_debits = sum(line.debit for line in payload.lines)
    total_credits = sum(line.credit for line in payload.lines)
    if total_debits != total_credits:
        raise HTTPException(
            status_code=400,
            detail=f"Journal entry is not balanced. Debits ({total_debits}) != Credits ({total_credits})",
        )

    if total_debits == 0:
        raise HTTPException(
            status_code=400,
            detail="Journal entry must have at least one debit and one credit amount",
        )

    # Validate all account_ids exist
    account_ids = [line.account_id for line in payload.lines]
    missing = []
    for aid in account_ids:
        if get_document(ACCOUNTS_COLLECTION, str(aid)) is None:
            missing.append(str(aid))
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Account(s) not found: {missing}",
        )

    entry_number = _generate_entry_number(store_id, payload.entry_date)

    now = datetime.now(timezone.utc)
    doc_id = str(_uuid.uuid4())
    lines_data = []
    for line_data in payload.lines:
        lines_data.append({
            "id": str(_uuid.uuid4()),
            "account_id": str(line_data.account_id),
            "debit": float(line_data.debit),
            "credit": float(line_data.credit),
            "description": line_data.description,
            "created_at": now,
        })

    entry_data = {
        "entry_number": entry_number,
        "entry_date": payload.entry_date.isoformat(),
        "description": payload.description,
        "store_id": str(store_id),
        "source_type": payload.source_type,
        "source_ref": payload.source_ref,
        "is_posted": False,
        "posted_by": None,
        "created_by": str(user.get("id")),
        "lines": lines_data,
        "created_at": now,
        "updated_at": now,
    }

    created = create_document(_je_collection(store_id), entry_data, doc_id=doc_id)
    return DataResponse(data=_entry_dict_to_read(created))


@router.get(
    "/api/stores/{store_id}/journal-entries",
    response_model=PaginatedResponse[JournalEntryRead],
)
async def list_journal_entries(
    store_id: UUID,
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    source_type: Optional[str] = Query(None),
    is_posted: Optional[bool] = Query(None),
    page: int = 1,
    page_size: int = 50,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    filters = []
    if source_type:
        filters.append(("source_type", "==", source_type))
    if is_posted is not None:
        filters.append(("is_posted", "==", is_posted))
    if date_from:
        filters.append(("entry_date", ">=", date_from.isoformat()))
    if date_to:
        filters.append(("entry_date", "<=", date_to.isoformat()))

    all_entries = query_collection(_je_collection(store_id), filters=filters, order_by="-entry_date")
    total = len(all_entries)
    offset = (page - 1) * page_size
    page_entries = all_entries[offset:offset + page_size]

    return PaginatedResponse(
        data=[_entry_dict_to_read(e) for e in page_entries],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/api/stores/{store_id}/journal-entries/{entry_id}",
    response_model=DataResponse[JournalEntryRead],
)
async def get_journal_entry(
    store_id: UUID,
    entry_id: UUID,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    entry = get_document(_je_collection(store_id), str(entry_id))
    if entry is None:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    return DataResponse(data=_entry_dict_to_read(entry))


@router.post(
    "/api/stores/{store_id}/journal-entries/{entry_id}/post",
    response_model=DataResponse[JournalEntryRead],
)
async def post_journal_entry(
    store_id: UUID,
    entry_id: UUID,
    role: dict = Depends(require_store_role(RoleEnum.owner)),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    entry = get_document(_je_collection(store_id), str(entry_id))
    if entry is None:
        raise HTTPException(status_code=404, detail="Journal entry not found")

    if entry.get("is_posted"):
        raise HTTPException(status_code=400, detail="Journal entry is already posted")

    updated = update_document(
        _je_collection(store_id),
        str(entry_id),
        {"is_posted": True, "posted_by": str(user.get("id")), "updated_at": datetime.now(timezone.utc)},
    )
    return DataResponse(data=_entry_dict_to_read(updated))


@router.delete(
    "/api/stores/{store_id}/journal-entries/{entry_id}",
    status_code=204,
)
async def delete_journal_entry(
    store_id: UUID,
    entry_id: UUID,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    entry = get_document(_je_collection(store_id), str(entry_id))
    if entry is None:
        raise HTTPException(status_code=404, detail="Journal entry not found")

    if entry.get("is_posted"):
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a posted journal entry",
        )

    delete_document(_je_collection(store_id), str(entry_id))


# ---------- Account Ledger ----------

@router.get(
    "/api/stores/{store_id}/accounts/{account_id}/ledger",
    response_model=DataResponse[list[LedgerEntry]],
)
async def get_account_ledger(
    store_id: UUID,
    account_id: UUID,
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    # Verify account exists
    if get_document(ACCOUNTS_COLLECTION, str(account_id)) is None:
        raise HTTPException(status_code=404, detail="Account not found")

    # Query all posted journal entries for this store
    filters = [("is_posted", "==", True)]
    if date_from:
        filters.append(("entry_date", ">=", date_from.isoformat()))
    if date_to:
        filters.append(("entry_date", "<=", date_to.isoformat()))

    entries = query_collection(_je_collection(store_id), filters=filters, order_by="entry_date")

    ledger = []
    account_id_str = str(account_id)
    for entry in entries:
        for line in entry.get("lines", []):
            if line.get("account_id") == account_id_str:
                entry_date = entry.get("entry_date")
                if isinstance(entry_date, str):
                    entry_date = date.fromisoformat(entry_date)
                ledger.append(LedgerEntry(
                    journal_entry_id=UUID(entry["id"]),
                    entry_number=entry.get("entry_number", ""),
                    entry_date=entry_date,
                    journal_description=entry.get("description", ""),
                    line_description=line.get("description"),
                    debit=Decimal(str(line.get("debit", 0))),
                    credit=Decimal(str(line.get("credit", 0))),
                    source_type=entry.get("source_type", "manual"),
                ))

    return DataResponse(data=ledger)


# ---------- Trial Balance ----------

@router.get(
    "/api/stores/{store_id}/trial-balance",
    response_model=DataResponse[list[AccountBalance]],
)
async def get_trial_balance(
    store_id: UUID,
    as_of: Optional[date] = Query(None),
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    # Get all active accounts
    accounts = query_collection(ACCOUNTS_COLLECTION, filters=[("is_active", "==", True)], order_by="code")

    # Query posted journal entries
    filters = [("is_posted", "==", True)]
    if as_of:
        filters.append(("entry_date", "<=", as_of.isoformat()))

    entries = query_collection(_je_collection(store_id), filters=filters)

    # Aggregate debit/credit by account_id from embedded lines
    sums: dict[str, tuple[Decimal, Decimal]] = {}
    for entry in entries:
        for line in entry.get("lines", []):
            aid = line.get("account_id", "")
            d = Decimal(str(line.get("debit", 0)))
            c = Decimal(str(line.get("credit", 0)))
            if aid in sums:
                sums[aid] = (sums[aid][0] + d, sums[aid][1] + c)
            else:
                sums[aid] = (d, c)

    balances = []
    for acct in accounts:
        acct_id_str = acct.get("id", "")
        debit_total, credit_total = sums.get(acct_id_str, (Decimal("0"), Decimal("0")))
        balance = debit_total - credit_total
        balances.append(AccountBalance(
            account_id=UUID(acct_id_str),
            account_name=acct.get("name", ""),
            account_code=acct.get("code", ""),
            account_type=acct.get("account_type", ""),
            debit_total=debit_total,
            credit_total=credit_total,
            balance=balance,
        ))

    return DataResponse(data=balances)
