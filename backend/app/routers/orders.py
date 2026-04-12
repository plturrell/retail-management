from __future__ import annotations

import uuid as uuid_mod
from datetime import UTC, date, datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.order import Order, OrderItem, OrderStatus
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.order import OrderCreate, OrderRead, OrderUpdate

router = APIRouter(prefix="/api/stores/{store_id}/orders", tags=["orders"])


def _generate_order_number() -> str:
    ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
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
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    subtotal = sum(item.line_total for item in payload.items)
    discount_total = sum(item.discount * item.qty for item in payload.items)
    tax_total = 0.0
    grand_total = subtotal - discount_total

    order = Order(
        order_number=_generate_order_number(),
        store_id=store_id,
        staff_id=payload.staff_id or user.id,
        order_date=payload.order_date or datetime.now(UTC),
        subtotal=subtotal,
        discount_total=discount_total,
        tax_total=tax_total,
        grand_total=grand_total,
        payment_method=payload.payment_method,
        payment_ref=payload.payment_ref,
        status=OrderStatus.open,
        source=payload.source,
    )
    db.add(order)
    await db.flush()

    for item_data in payload.items:
        order_item = OrderItem(
            order_id=order.id,
            **item_data.model_dump(),
        )
        db.add(order_item)

    await db.flush()
    await db.refresh(order)
    return DataResponse(data=OrderRead.model_validate(order))


@router.patch("/{order_id}", response_model=DataResponse[OrderRead])
async def update_order(
    store_id: UUID,
    order_id: UUID,
    payload: OrderUpdate,
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
