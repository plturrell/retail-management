from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.purchase import (
    Expense,
    ExpenseCategory,
    GoodsReceipt,
    GoodsReceiptItem,
    GoodsReceiptStatus,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
)
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.purchase import (
    ExpenseCategoryCreate,
    ExpenseCategoryRead,
    ExpenseCategoryUpdate,
    ExpenseCreate,
    ExpenseRead,
    ExpenseUpdate,
    GoodsReceiptCreate,
    GoodsReceiptRead,
    GoodsReceiptUpdate,
    PurchaseOrderCreate,
    PurchaseOrderRead,
    PurchaseOrderUpdate,
)

router = APIRouter(prefix="/api", tags=["purchases"])

_po_router = APIRouter(prefix="/purchase-orders")
_grn_router = APIRouter(prefix="/goods-receipts")
_expense_router = APIRouter(prefix="/expenses")
_expense_cat_router = APIRouter(prefix="/expense-categories")


def _next_po_number() -> str:
    return f"PO-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


def _next_grn_number() -> str:
    return f"GRN-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


def _next_expense_number() -> str:
    return f"EXP-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


# ------------------------------------------------------------------ #
# Purchase Orders                                                     #
# ------------------------------------------------------------------ #

@_po_router.get("", response_model=PaginatedResponse[PurchaseOrderRead])
async def list_purchase_orders(
    page: int = 1,
    page_size: int = 50,
    store_id: UUID | None = None,
    supplier_id: UUID | None = None,
    status: PurchaseOrderStatus | None = None,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(PurchaseOrder)
    if store_id:
        q = q.where(PurchaseOrder.store_id == store_id)
    if supplier_id:
        q = q.where(PurchaseOrder.supplier_id == supplier_id)
    if status:
        q = q.where(PurchaseOrder.status == status)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    result = await db.execute(q.order_by(PurchaseOrder.order_date.desc()).offset((page - 1) * page_size).limit(page_size))
    return PaginatedResponse(
        data=[PurchaseOrderRead.model_validate(po) for po in result.scalars().all()],
        total=total,
        page=page,
        page_size=page_size,
    )


@_po_router.get("/{po_id}", response_model=DataResponse[PurchaseOrderRead])
async def get_purchase_order(
    po_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id))
    po = result.scalar_one_or_none()
    if po is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return DataResponse(data=PurchaseOrderRead.model_validate(po))


@_po_router.post("", response_model=DataResponse[PurchaseOrderRead], status_code=201)
async def create_purchase_order(
    payload: PurchaseOrderCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items_data = payload.model_dump(exclude={"items"})
    po = PurchaseOrder(
        **items_data,
        po_number=_next_po_number(),
        created_by=user.id,
    )
    subtotal = 0.0
    for item_payload in payload.items:
        line_total = item_payload.qty_ordered * item_payload.unit_cost
        subtotal += line_total
        item = PurchaseOrderItem(
            sku_id=item_payload.sku_id,
            qty_ordered=item_payload.qty_ordered,
            unit_cost=item_payload.unit_cost,
            tax_code=item_payload.tax_code,
            line_total=line_total,
        )
        po.items.append(item)

    po.subtotal = subtotal
    po.grand_total = subtotal  # Tax calculation can be added separately
    db.add(po)
    await db.flush()
    await db.refresh(po)
    return DataResponse(data=PurchaseOrderRead.model_validate(po))


@_po_router.patch("/{po_id}", response_model=DataResponse[PurchaseOrderRead])
async def update_purchase_order(
    po_id: UUID,
    payload: PurchaseOrderUpdate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id))
    po = result.scalar_one_or_none()
    if po is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if po.status in (PurchaseOrderStatus.fully_received, PurchaseOrderStatus.cancelled):
        raise HTTPException(status_code=400, detail=f"Cannot update a {po.status.value} purchase order")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(po, key, value)
    await db.flush()
    await db.refresh(po)
    return DataResponse(data=PurchaseOrderRead.model_validate(po))


# ------------------------------------------------------------------ #
# Goods Receipts                                                      #
# ------------------------------------------------------------------ #

@_grn_router.get("", response_model=PaginatedResponse[GoodsReceiptRead])
async def list_goods_receipts(
    page: int = 1,
    page_size: int = 50,
    store_id: UUID | None = None,
    po_id: UUID | None = None,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(GoodsReceipt)
    if store_id:
        q = q.where(GoodsReceipt.store_id == store_id)
    if po_id:
        q = q.where(GoodsReceipt.purchase_order_id == po_id)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    result = await db.execute(q.order_by(GoodsReceipt.received_date.desc()).offset((page - 1) * page_size).limit(page_size))
    return PaginatedResponse(
        data=[GoodsReceiptRead.model_validate(g) for g in result.scalars().all()],
        total=total,
        page=page,
        page_size=page_size,
    )


@_grn_router.get("/{grn_id}", response_model=DataResponse[GoodsReceiptRead])
async def get_goods_receipt(
    grn_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(GoodsReceipt).where(GoodsReceipt.id == grn_id))
    grn = result.scalar_one_or_none()
    if grn is None:
        raise HTTPException(status_code=404, detail="Goods receipt not found")
    return DataResponse(data=GoodsReceiptRead.model_validate(grn))


@_grn_router.post("", response_model=DataResponse[GoodsReceiptRead], status_code=201)
async def create_goods_receipt(
    payload: GoodsReceiptCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    grn = GoodsReceipt(
        **payload.model_dump(exclude={"items"}),
        grn_number=_next_grn_number(),
        received_by=user.id,
    )
    for item_payload in payload.items:
        item = GoodsReceiptItem(**item_payload.model_dump(), goods_receipt_id=grn.id)
        # Update qty_received on the PO item
        po_item_result = await db.execute(
            select(PurchaseOrderItem).where(PurchaseOrderItem.id == item_payload.po_item_id)
        )
        po_item = po_item_result.scalar_one_or_none()
        if po_item:
            po_item.qty_received = min(
                po_item.qty_ordered,
                po_item.qty_received + item_payload.qty_received,
            )
        grn.items.append(item)

    db.add(grn)
    await db.flush()
    await db.refresh(grn)
    return DataResponse(data=GoodsReceiptRead.model_validate(grn))


# ------------------------------------------------------------------ #
# Expense Categories                                                  #
# ------------------------------------------------------------------ #

@_expense_cat_router.get("", response_model=DataResponse[list[ExpenseCategoryRead]])
async def list_expense_categories(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ExpenseCategory).where(ExpenseCategory.is_active == True))
    return DataResponse(data=[ExpenseCategoryRead.model_validate(c) for c in result.scalars().all()])


@_expense_cat_router.post("", response_model=DataResponse[ExpenseCategoryRead], status_code=201)
async def create_expense_category(
    payload: ExpenseCategoryCreate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cat = ExpenseCategory(**payload.model_dump())
    db.add(cat)
    await db.flush()
    await db.refresh(cat)
    return DataResponse(data=ExpenseCategoryRead.model_validate(cat))


@_expense_cat_router.patch("/{category_id}", response_model=DataResponse[ExpenseCategoryRead])
async def update_expense_category(
    category_id: UUID,
    payload: ExpenseCategoryUpdate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ExpenseCategory).where(ExpenseCategory.id == category_id))
    cat = result.scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=404, detail="Expense category not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(cat, key, value)
    await db.flush()
    await db.refresh(cat)
    return DataResponse(data=ExpenseCategoryRead.model_validate(cat))


# ------------------------------------------------------------------ #
# Expenses                                                            #
# ------------------------------------------------------------------ #

@_expense_router.get("", response_model=PaginatedResponse[ExpenseRead])
async def list_expenses(
    page: int = 1,
    page_size: int = 50,
    store_id: UUID | None = None,
    category_id: UUID | None = None,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Expense)
    if store_id:
        q = q.where(Expense.store_id == store_id)
    if category_id:
        q = q.where(Expense.category_id == category_id)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    result = await db.execute(q.order_by(Expense.expense_date.desc()).offset((page - 1) * page_size).limit(page_size))
    return PaginatedResponse(
        data=[ExpenseRead.model_validate(e) for e in result.scalars().all()],
        total=total,
        page=page,
        page_size=page_size,
    )


@_expense_router.get("/{expense_id}", response_model=DataResponse[ExpenseRead])
async def get_expense(
    expense_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Expense).where(Expense.id == expense_id))
    expense = result.scalar_one_or_none()
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    return DataResponse(data=ExpenseRead.model_validate(expense))


@_expense_router.post("", response_model=DataResponse[ExpenseRead], status_code=201)
async def create_expense(
    payload: ExpenseCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    expense = Expense(
        **payload.model_dump(),
        expense_number=_next_expense_number(),
        submitted_by=user.id,
    )
    db.add(expense)
    await db.flush()
    await db.refresh(expense)
    return DataResponse(data=ExpenseRead.model_validate(expense))


@_expense_router.patch("/{expense_id}", response_model=DataResponse[ExpenseRead])
async def update_expense(
    expense_id: UUID,
    payload: ExpenseUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Expense).where(Expense.id == expense_id))
    expense = result.scalar_one_or_none()
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    updates = payload.model_dump(exclude_unset=True)
    if "status" in updates and updates["status"] in ("approved", "rejected"):
        expense.approved_by = user.id
        expense.approved_at = datetime.now(timezone.utc)
    for key, value in updates.items():
        setattr(expense, key, value)
    await db.flush()
    await db.refresh(expense)
    return DataResponse(data=ExpenseRead.model_validate(expense))


# Mount sub-routers
router.include_router(_po_router)
router.include_router(_grn_router)
router.include_router(_expense_cat_router)
router.include_router(_expense_router)
