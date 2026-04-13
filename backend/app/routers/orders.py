from __future__ import annotations

import uuid as uuid_mod
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.inventory import SKU
from app.models.order import Order, OrderItem, OrderStatus
from app.models.user import RoleEnum, User, UserStoreRole
from app.auth.dependencies import get_current_user, require_store_access, require_store_role
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.order import OrderCreate, OrderRead, OrderUpdate
from app.services.inventory_logic import deduct_stock_for_order
from app.services.promotions import best_discount_for_sku
from app.services.tax import compute_line_tax

router = APIRouter(prefix="/api/stores/{store_id}/orders", tags=["orders"])


def _generate_order_number() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid_mod.uuid4().hex[:6].upper()
    return f"ORD-{ts}-{short}"


@router.get("", response_model=PaginatedResponse[OrderRead])
async def list_orders(
    store_id: UUID,
    page: int = 1,
    page_size: int = 50,
    status: Optional[str] = None,
    source: Optional[str] = None,
    payment_method: Optional[str] = None,
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    _: UserStoreRole = Depends(require_store_access),
    db: AsyncSession = Depends(get_db),
):
    base = select(Order).where(Order.store_id == store_id)
    if status:
        base = base.where(Order.status == status)
    if source:
        base = base.where(Order.source == source)
    if payment_method:
        base = base.where(Order.payment_method == payment_method)
    if date_from:
        base = base.where(Order.order_date >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        base = base.where(Order.order_date <= datetime.combine(date_to, datetime.max.time()))

    count_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = count_result.scalar() or 0

    query = base.order_by(Order.order_date.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    orders = result.scalars().all()

    return PaginatedResponse(
        data=[OrderRead.model_validate(o) for o in orders],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{order_id}", response_model=DataResponse[OrderRead])
async def get_order(
    store_id: UUID,
    order_id: UUID,
    _: UserStoreRole = Depends(require_store_access),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Order).where(Order.id == order_id, Order.store_id == store_id)
    )
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return DataResponse(data=OrderRead.model_validate(order))


@router.post("", response_model=DataResponse[OrderRead], status_code=201)
async def create_order(
    store_id: UUID,
    payload: OrderCreate,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.staff)),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if payload.store_id != store_id:
        raise HTTPException(status_code=400, detail="Payload store_id must match route store_id")

    # ── 1. Build line items with auto-applied promotions & GST ───
    subtotal = 0.0
    discount_total = 0.0
    tax_total = 0.0
    line_items: list[dict] = []

    for item in payload.items:
        # Look up SKU for tax_code and category
        sku_result = await db.execute(
            select(SKU).where(SKU.id == item.sku_id, SKU.store_id == store_id)
        )
        sku = sku_result.scalar_one_or_none()
        if sku is None:
            raise HTTPException(
                status_code=400,
                detail=f"SKU {item.sku_id} is not available in this store",
            )
        if sku.block_sales:
            raise HTTPException(
                status_code=400,
                detail=f"SKU {item.sku_id} is blocked for sales",
            )
        tax_code = sku.tax_code
        category_id = sku.category_id

        # Auto-apply best promotion if no explicit discount was given
        if item.discount == 0:
            promo_discount = await best_discount_for_sku(
                db, item.sku_id, category_id, item.unit_price, item.qty
            )
        else:
            promo_discount = item.discount

        line_total = round((item.unit_price - promo_discount) * item.qty, 2)
        if round(item.line_total, 2) != line_total:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid line_total for SKU {item.sku_id}",
            )
        line_tax = compute_line_tax(item.unit_price, item.qty, promo_discount, tax_code)

        subtotal += item.unit_price * item.qty
        discount_total += promo_discount * item.qty
        tax_total += line_tax

        line_items.append({
            "sku_id": item.sku_id,
            "qty": item.qty,
            "unit_price": item.unit_price,
            "discount": promo_discount,
            "line_total": line_total,
        })

    grand_total = round(subtotal - discount_total, 2)

    # ── 2. Create order header ───────────────────────────────────
    order = Order(
        order_number=_generate_order_number(),
        store_id=store_id,
        staff_id=payload.staff_id or user.id,
        order_date=payload.order_date or datetime.now(timezone.utc),
        subtotal=round(subtotal, 2),
        discount_total=round(discount_total, 2),
        tax_total=round(tax_total, 2),
        grand_total=grand_total,
        payment_method=payload.payment_method,
        payment_ref=payload.payment_ref,
        status=OrderStatus.open,
        source=payload.source,
    )
    db.add(order)
    await db.flush()

    # ── 3. Create line items ─────────────────────────────────────
    for li in line_items:
        order_item = OrderItem(order_id=order.id, **li)
        db.add(order_item)

    # ── 4. Deduct inventory ──────────────────────────────────────
    stock_warnings = await deduct_stock_for_order(db, store_id, line_items)

    await db.flush()
    await db.refresh(order)
    return DataResponse(data=OrderRead.model_validate(order))


@router.patch("/{order_id}", response_model=DataResponse[OrderRead])
async def update_order(
    store_id: UUID,
    order_id: UUID,
    payload: OrderUpdate,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.staff)),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Order).where(Order.id == order_id, Order.store_id == store_id)
    )
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(order, key, value)

    await db.flush()
    await db.refresh(order)
    return DataResponse(data=OrderRead.model_validate(order))
