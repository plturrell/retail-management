from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.finance import Account, AccountType, JournalEntry, JournalLine
from app.models.user import RoleEnum, User, UserStoreRole
from app.auth.dependencies import (
    get_current_user,
    require_store_access,
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


# ---------- Chart of Accounts ----------

@router.post("/api/accounts", response_model=DataResponse[AccountRead], status_code=201)
async def create_account(
    payload: AccountCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Validate account_type
    try:
        acct_type = AccountType(payload.account_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid account_type: {payload.account_type}. Must be one of: asset, liability, equity, revenue, expense",
        )

    # Check for duplicate code
    existing = await db.execute(
        select(Account).where(Account.code == payload.code)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Account code '{payload.code}' already exists")

    account = Account(
        code=payload.code,
        name=payload.name,
        account_type=acct_type,
        parent_id=payload.parent_id,
        description=payload.description,
        is_active=payload.is_active,
        store_id=payload.store_id,
    )
    db.add(account)
    await db.flush()
    await db.refresh(account)
    return DataResponse(data=AccountRead.model_validate(account))


@router.get("/api/accounts", response_model=DataResponse[list[AccountRead]])
async def list_accounts(
    account_type: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Account).order_by(Account.code)
    if account_type:
        try:
            acct_type = AccountType(account_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid account_type: {account_type}")
        query = query.where(Account.account_type == acct_type)
    if is_active is not None:
        query = query.where(Account.is_active == is_active)

    result = await db.execute(query)
    accounts = result.scalars().all()
    return DataResponse(data=[AccountRead.model_validate(a) for a in accounts])


@router.get("/api/accounts/{account_id}", response_model=DataResponse[AccountRead])
async def get_account(
    account_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Account).where(Account.id == account_id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return DataResponse(data=AccountRead.model_validate(account))


@router.patch("/api/accounts/{account_id}", response_model=DataResponse[AccountRead])
async def update_account(
    account_id: UUID,
    payload: AccountUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Account).where(Account.id == account_id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(account, key, value)

    await db.flush()
    await db.refresh(account)
    return DataResponse(data=AccountRead.model_validate(account))


DEFAULT_CHART_OF_ACCOUNTS = [
    # Assets (1xxx)
    ("1000", "Cash", AccountType.asset, None),
    ("1010", "OCBC Bank Account", AccountType.asset, None),
    ("1020", "HiPay Settlement", AccountType.asset, None),
    ("1030", "Airwallex Settlement", AccountType.asset, None),
    ("1100", "Accounts Receivable", AccountType.asset, None),
    ("1200", "Inventory Asset", AccountType.asset, None),
    ("1300", "Prepaid Expenses", AccountType.asset, None),
    # Liabilities (2xxx)
    ("2000", "Accounts Payable", AccountType.liability, None),
    ("2100", "CPF Payable", AccountType.liability, None),
    ("2200", "Salary Payable", AccountType.liability, None),
    ("2300", "Accrued Expenses", AccountType.liability, None),
    # Equity (3xxx)
    ("3000", "Owner's Equity", AccountType.equity, None),
    ("3100", "Retained Earnings", AccountType.equity, None),
    # Revenue (4xxx)
    ("4000", "Sales Revenue", AccountType.revenue, None),
    ("4010", "Sales - Jewellery", AccountType.revenue, "4000"),
    ("4020", "Sales - Homeware", AccountType.revenue, "4000"),
    ("4100", "Other Income", AccountType.revenue, None),
    # Expenses (5xxx)
    ("5000", "Cost of Goods Sold", AccountType.expense, None),
    ("5100", "Salary Expense", AccountType.expense, None),
    ("5110", "CPF Expense (Employer)", AccountType.expense, "5100"),
    ("5200", "Rent Expense", AccountType.expense, None),
    ("5300", "Utilities", AccountType.expense, None),
    ("5400", "Marketing", AccountType.expense, None),
    ("5500", "Bank Charges", AccountType.expense, None),
    ("5600", "Other Expenses", AccountType.expense, None),
]


@router.post("/api/accounts/seed", response_model=DataResponse[list[AccountRead]], status_code=201)
async def seed_chart_of_accounts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Check if accounts already seeded
    existing = await db.execute(select(func.count()).select_from(Account))
    count = existing.scalar() or 0
    if count > 0:
        raise HTTPException(
            status_code=409,
            detail="Chart of accounts already seeded. Delete existing accounts first.",
        )

    # First pass: create all accounts without parent links
    code_to_account = {}
    for code, name, acct_type, _parent_code in DEFAULT_CHART_OF_ACCOUNTS:
        account = Account(
            code=code,
            name=name,
            account_type=acct_type,
            is_active=True,
        )
        db.add(account)
        code_to_account[code] = account

    await db.flush()

    # Second pass: set parent_id for sub-accounts
    for code, _name, _acct_type, parent_code in DEFAULT_CHART_OF_ACCOUNTS:
        if parent_code and parent_code in code_to_account:
            code_to_account[code].parent_id = code_to_account[parent_code].id

    await db.flush()

    # Refresh all and return
    for account in code_to_account.values():
        await db.refresh(account)

    accounts = sorted(code_to_account.values(), key=lambda a: a.code)
    return DataResponse(data=[AccountRead.model_validate(a) for a in accounts])


# ---------- Journal Entries ----------

async def _generate_entry_number(db: AsyncSession, entry_date: date) -> str:
    """Generate a unique entry number like JE-YYYYMMDD-001."""
    date_str = entry_date.strftime("%Y%m%d")
    prefix = f"JE-{date_str}-"

    result = await db.execute(
        select(func.count())
        .select_from(JournalEntry)
        .where(JournalEntry.entry_number.like(f"{prefix}%"))
    )
    count = (result.scalar() or 0) + 1
    return f"{prefix}{count:03d}"


@router.post(
    "/api/stores/{store_id}/journal-entries",
    response_model=DataResponse[JournalEntryRead],
    status_code=201,
)
async def create_journal_entry(
    store_id: UUID,
    payload: JournalEntryCreate,
    role: UserStoreRole = Depends(require_store_access),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Validate debits = credits
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
    result = await db.execute(
        select(Account.id).where(Account.id.in_(account_ids))
    )
    found_ids = {row[0] for row in result.all()}
    missing = set(account_ids) - found_ids
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Account(s) not found: {[str(m) for m in missing]}",
        )

    entry_number = await _generate_entry_number(db, payload.entry_date)

    entry = JournalEntry(
        entry_number=entry_number,
        entry_date=payload.entry_date,
        description=payload.description,
        store_id=store_id,
        source_type=payload.source_type,
        source_ref=payload.source_ref,
        created_by=user.id,
    )
    db.add(entry)
    await db.flush()

    for line_data in payload.lines:
        line = JournalLine(
            journal_entry_id=entry.id,
            account_id=line_data.account_id,
            debit=float(line_data.debit),
            credit=float(line_data.credit),
            description=line_data.description,
        )
        db.add(line)

    await db.flush()

    # Reload with lines
    result = await db.execute(
        select(JournalEntry)
        .options(selectinload(JournalEntry.lines))
        .where(JournalEntry.id == entry.id)
    )
    entry = result.scalar_one()

    return DataResponse(data=_entry_to_read(entry))


def _entry_to_read(entry: JournalEntry) -> JournalEntryRead:
    """Convert a JournalEntry ORM object to a JournalEntryRead schema."""
    lines = []
    for line in entry.lines:
        lines.append(JournalLineRead(
            id=line.id,
            journal_entry_id=line.journal_entry_id,
            account_id=line.account_id,
            debit=Decimal(str(line.debit)),
            credit=Decimal(str(line.credit)),
            description=line.description,
            account_name=None,
            created_at=line.created_at,
        ))
    return JournalEntryRead(
        id=entry.id,
        entry_number=entry.entry_number,
        entry_date=entry.entry_date,
        description=entry.description,
        store_id=entry.store_id,
        source_type=entry.source_type,
        source_ref=entry.source_ref,
        is_posted=entry.is_posted,
        posted_by=entry.posted_by,
        created_by=entry.created_by,
        lines=lines,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


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
    _: UserStoreRole = Depends(require_store_access),
    db: AsyncSession = Depends(get_db),
):
    base = select(JournalEntry).where(JournalEntry.store_id == store_id)
    if date_from:
        base = base.where(JournalEntry.entry_date >= date_from)
    if date_to:
        base = base.where(JournalEntry.entry_date <= date_to)
    if source_type:
        base = base.where(JournalEntry.source_type == source_type)
    if is_posted is not None:
        base = base.where(JournalEntry.is_posted == is_posted)

    count_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = count_result.scalar() or 0

    query = (
        base.options(selectinload(JournalEntry.lines))
        .order_by(JournalEntry.entry_date.desc(), JournalEntry.entry_number.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    entries = result.scalars().unique().all()

    return PaginatedResponse(
        data=[_entry_to_read(e) for e in entries],
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
    _: UserStoreRole = Depends(require_store_access),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(JournalEntry)
        .options(selectinload(JournalEntry.lines))
        .where(JournalEntry.id == entry_id, JournalEntry.store_id == store_id)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Journal entry not found")

    return DataResponse(data=_entry_to_read(entry))


@router.post(
    "/api/stores/{store_id}/journal-entries/{entry_id}/post",
    response_model=DataResponse[JournalEntryRead],
)
async def post_journal_entry(
    store_id: UUID,
    entry_id: UUID,
    role: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(JournalEntry)
        .options(selectinload(JournalEntry.lines))
        .where(JournalEntry.id == entry_id, JournalEntry.store_id == store_id)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Journal entry not found")

    if entry.is_posted:
        raise HTTPException(status_code=400, detail="Journal entry is already posted")

    entry.is_posted = True
    entry.posted_by = user.id

    await db.flush()
    await db.refresh(entry)

    return DataResponse(data=_entry_to_read(entry))


@router.delete(
    "/api/stores/{store_id}/journal-entries/{entry_id}",
    status_code=204,
)
async def delete_journal_entry(
    store_id: UUID,
    entry_id: UUID,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(JournalEntry).where(
            JournalEntry.id == entry_id, JournalEntry.store_id == store_id
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Journal entry not found")

    if entry.is_posted:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a posted journal entry",
        )

    await db.delete(entry)


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
    _: UserStoreRole = Depends(require_store_access),
    db: AsyncSession = Depends(get_db),
):
    # Verify account exists
    acct_result = await db.execute(
        select(Account).where(Account.id == account_id)
    )
    if acct_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Account not found")

    query = (
        select(JournalLine, JournalEntry)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(
            JournalLine.account_id == account_id,
            JournalEntry.store_id == store_id,
            JournalEntry.is_posted == True,
        )
    )
    if date_from:
        query = query.where(JournalEntry.entry_date >= date_from)
    if date_to:
        query = query.where(JournalEntry.entry_date <= date_to)

    query = query.order_by(JournalEntry.entry_date, JournalEntry.entry_number)

    result = await db.execute(query)
    rows = result.all()

    ledger = []
    for line, entry in rows:
        ledger.append(LedgerEntry(
            journal_entry_id=entry.id,
            entry_number=entry.entry_number,
            entry_date=entry.entry_date,
            journal_description=entry.description,
            line_description=line.description,
            debit=Decimal(str(line.debit)),
            credit=Decimal(str(line.credit)),
            source_type=entry.source_type,
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
    _: UserStoreRole = Depends(require_store_access),
    db: AsyncSession = Depends(get_db),
):
    # Get all active accounts
    acct_result = await db.execute(
        select(Account).where(Account.is_active == True).order_by(Account.code)
    )
    accounts = acct_result.scalars().all()

    # Build the query for sums
    sum_query = (
        select(
            JournalLine.account_id,
            func.coalesce(func.sum(JournalLine.debit), 0).label("total_debit"),
            func.coalesce(func.sum(JournalLine.credit), 0).label("total_credit"),
        )
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(
            JournalEntry.store_id == store_id,
            JournalEntry.is_posted == True,
        )
        .group_by(JournalLine.account_id)
    )
    if as_of:
        sum_query = sum_query.where(JournalEntry.entry_date <= as_of)

    sum_result = await db.execute(sum_query)
    sums = {row[0]: (Decimal(str(row[1])), Decimal(str(row[2]))) for row in sum_result.all()}

    balances = []
    for acct in accounts:
        debit_total, credit_total = sums.get(acct.id, (Decimal("0"), Decimal("0")))
        balance = debit_total - credit_total
        balances.append(AccountBalance(
            account_id=acct.id,
            account_name=acct.name,
            account_code=acct.code,
            account_type=acct.account_type.value,
            debit_total=debit_total,
            credit_total=credit_total,
            balance=balance,
        ))

    return DataResponse(data=balances)
