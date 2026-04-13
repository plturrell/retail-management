from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.inventory import SKU, Category, Brand
from app.models.order import Order, OrderItem, OrderStatus, SalespersonAlias
from app.models.user import User, RoleEnum
from app.auth.dependencies import get_current_user, require_store_role
from app.schemas.common import DataResponse
from app.schemas.order import (
    SalespersonAliasCreate,
    SalespersonAliasRead,
    StaffSalesSummary,
)

router = APIRouter(prefix="/api/stores/{store_id}/sales", tags=["sales"])


class PaymentMethodBreakdown(BaseModel):
    payment_method: str
    total: float
    count: int


class DailySalesSummary(BaseModel):
    date: str
    total_sales: float
    order_count: int
    avg_order_value: float
    by_payment_method: list[PaymentMethodBreakdown]


class DateRangeSummary(BaseModel):
    from_date: str
    to_date: str
    total_sales: float
    order_count: int
    avg_order_value: float
    daily: list[DailySalesSummary]


class CategorySales(BaseModel):
    category_id: Optional[str] = None
    category_name: str
    total_sales: float
    qty_sold: int


class BrandSales(BaseModel):
    brand_id: Optional[str] = None
    brand_name: str
    total_sales: float
    qty_sold: int


@router.get("/daily", response_model=DailySalesSummary)
async def daily_sales(
    store_id: UUID,
    date: date = Query(..., alias="date"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Daily summary: total sales, order count, avg order value, breakdown by payment method."""
    day_start = datetime.combine(date, datetime.min.time())
    day_end = datetime.combine(date, datetime.max.time())

    base = select(Order).where(
        Order.store_id == store_id,
        Order.order_date >= day_start,
        Order.order_date <= day_end,
        Order.status != OrderStatus.voided,
    )

    result = await db.execute(base)
    orders = result.scalars().all()

    total_sales = sum(float(o.grand_total) for o in orders)
    order_count = len(orders)
    avg_order_value = total_sales / order_count if order_count > 0 else 0.0

    # Group by payment method
    pm_map: dict[str, dict] = {}
    for o in orders:
        pm = o.payment_method
        if pm not in pm_map:
            pm_map[pm] = {"total": 0.0, "count": 0}
        pm_map[pm]["total"] += float(o.grand_total)
        pm_map[pm]["count"] += 1

    by_payment = [
        PaymentMethodBreakdown(payment_method=k, total=v["total"], count=v["count"])
        for k, v in pm_map.items()
    ]

    return DailySalesSummary(
        date=str(date),
        total_sales=round(total_sales, 2),
        order_count=order_count,
        avg_order_value=round(avg_order_value, 2),
        by_payment_method=by_payment,
    )


@router.get("/summary", response_model=DateRangeSummary)
async def sales_summary(
    store_id: UUID,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Date range summary with daily breakdown."""
    range_start = datetime.combine(from_date, datetime.min.time())
    range_end = datetime.combine(to_date, datetime.max.time())

    base = select(Order).where(
        Order.store_id == store_id,
        Order.order_date >= range_start,
        Order.order_date <= range_end,
        Order.status != OrderStatus.voided,
    )
    result = await db.execute(base)
    orders = result.scalars().all()

    total_sales = sum(float(o.grand_total) for o in orders)
    order_count = len(orders)
    avg_order_value = total_sales / order_count if order_count > 0 else 0.0

    # Build daily breakdown
    daily_map: dict[str, list] = {}
    for o in orders:
        day_key = o.order_date.date().isoformat()
        if day_key not in daily_map:
            daily_map[day_key] = []
        daily_map[day_key].append(o)

    daily_summaries = []
    current = from_date
    while current <= to_date:
        day_key = current.isoformat()
        day_orders = daily_map.get(day_key, [])
        day_total = sum(float(o.grand_total) for o in day_orders)
        day_count = len(day_orders)
        day_avg = day_total / day_count if day_count > 0 else 0.0

        pm_map: dict[str, dict] = {}
        for o in day_orders:
            pm = o.payment_method
            if pm not in pm_map:
                pm_map[pm] = {"total": 0.0, "count": 0}
            pm_map[pm]["total"] += float(o.grand_total)
            pm_map[pm]["count"] += 1

        by_payment = [
            PaymentMethodBreakdown(payment_method=k, total=v["total"], count=v["count"])
            for k, v in pm_map.items()
        ]

        daily_summaries.append(DailySalesSummary(
            date=day_key,
            total_sales=round(day_total, 2),
            order_count=day_count,
            avg_order_value=round(day_avg, 2),
            by_payment_method=by_payment,
        ))
        current += timedelta(days=1)

    return DateRangeSummary(
        from_date=str(from_date),
        to_date=str(to_date),
        total_sales=round(total_sales, 2),
        order_count=order_count,
        avg_order_value=round(avg_order_value, 2),
        daily=daily_summaries,
    )


@router.get("/by-category", response_model=list[CategorySales])
async def sales_by_category(
    store_id: UUID,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sales grouped by category for a date range."""
    range_start = datetime.combine(from_date, datetime.min.time())
    range_end = datetime.combine(to_date, datetime.max.time())

    query = (
        select(
            Category.id,
            Category.description,
            func.sum(OrderItem.line_total).label("total_sales"),
            func.sum(OrderItem.qty).label("qty_sold"),
        )
        .select_from(OrderItem)
        .join(Order, OrderItem.order_id == Order.id)
        .join(SKU, OrderItem.sku_id == SKU.id)
        .outerjoin(Category, SKU.category_id == Category.id)
        .where(
            Order.store_id == store_id,
            Order.order_date >= range_start,
            Order.order_date <= range_end,
            Order.status != OrderStatus.voided,
        )
        .group_by(Category.id, Category.description)
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        CategorySales(
            category_id=str(row[0]) if row[0] else None,
            category_name=row[1] or "Uncategorized",
            total_sales=float(row[2] or 0),
            qty_sold=int(row[3] or 0),
        )
        for row in rows
    ]


@router.get("/by-brand", response_model=list[BrandSales])
async def sales_by_brand(
    store_id: UUID,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sales grouped by brand for a date range."""
    range_start = datetime.combine(from_date, datetime.min.time())
    range_end = datetime.combine(to_date, datetime.max.time())

    query = (
        select(
            Brand.id,
            Brand.name,
            func.sum(OrderItem.line_total).label("total_sales"),
            func.sum(OrderItem.qty).label("qty_sold"),
        )
        .select_from(OrderItem)
        .join(Order, OrderItem.order_id == Order.id)
        .join(SKU, OrderItem.sku_id == SKU.id)
        .outerjoin(Brand, SKU.brand_id == Brand.id)
        .where(
            Order.store_id == store_id,
            Order.order_date >= range_start,
            Order.order_date <= range_end,
            Order.status != OrderStatus.voided,
        )
        .group_by(Brand.id, Brand.name)
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        BrandSales(
            brand_id=str(row[0]) if row[0] else None,
            brand_name=row[1] or "Unbranded",
            total_sales=float(row[2] or 0),
            qty_sold=int(row[3] or 0),
        )
        for row in rows
    ]



# ─── Sales by Staff ────────────────────────────────────────────────


@router.get("/by-staff", response_model=DataResponse[list[StaffSalesSummary]])
async def sales_by_staff(
    store_id: UUID,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sales grouped by salesperson_id with totals for a date range."""
    range_start = datetime.combine(from_date, datetime.min.time())
    range_end = datetime.combine(to_date, datetime.max.time())

    query = (
        select(
            Order.salesperson_id,
            func.sum(Order.grand_total).label("total_sales"),
            func.count(Order.id).label("order_count"),
        )
        .where(
            Order.store_id == store_id,
            Order.order_date >= range_start,
            Order.order_date <= range_end,
            Order.status != OrderStatus.voided,
        )
        .group_by(Order.salesperson_id)
    )

    result = await db.execute(query)
    rows = result.all()

    # Build a lookup of user IDs to names
    sp_ids = [row[0] for row in rows if row[0] is not None]
    name_map: dict[UUID, str] = {}
    if sp_ids:
        user_result = await db.execute(
            select(User.id, User.full_name).where(User.id.in_(sp_ids))
        )
        name_map = {uid: name for uid, name in user_result.all()}

    summaries = []
    for row in rows:
        sp_id = row[0]
        total = float(row[1] or 0)
        count = int(row[2] or 0)
        avg = total / count if count > 0 else 0.0
        summaries.append(
            StaffSalesSummary(
                salesperson_id=sp_id,
                salesperson_name=name_map.get(sp_id) if sp_id else None,
                total_sales=round(total, 2),
                order_count=count,
                avg_order_value=round(avg, 2),
            )
        )

    return DataResponse(data=summaries)


# ─── Salesperson Aliases CRUD ──────────────────────────────────────


@router.post(
    "/salesperson-aliases",
    response_model=DataResponse[SalespersonAliasRead],
    status_code=201,
)
async def create_salesperson_alias(
    store_id: UUID,
    payload: SalespersonAliasCreate,
    _=Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    """Create a salesperson alias for OCR name matching."""
    alias = SalespersonAlias(
        alias_name=payload.alias_name,
        user_id=payload.user_id,
        store_id=store_id,
    )
    db.add(alias)
    await db.flush()
    await db.refresh(alias)
    return DataResponse(data=SalespersonAliasRead.model_validate(alias))


@router.get(
    "/salesperson-aliases",
    response_model=DataResponse[list[SalespersonAliasRead]],
)
async def list_salesperson_aliases(
    store_id: UUID,
    _=Depends(require_store_role(RoleEnum.staff)),
    db: AsyncSession = Depends(get_db),
):
    """List all salesperson aliases for a store."""
    result = await db.execute(
        select(SalespersonAlias).where(SalespersonAlias.store_id == store_id)
    )
    aliases = result.scalars().all()
    return DataResponse(data=[SalespersonAliasRead.model_validate(a) for a in aliases])


@router.delete("/salesperson-aliases/{alias_id}", status_code=204)
async def delete_salesperson_alias(
    store_id: UUID,
    alias_id: UUID,
    _=Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    """Delete a salesperson alias."""
    result = await db.execute(
        select(SalespersonAlias).where(
            SalespersonAlias.id == alias_id,
            SalespersonAlias.store_id == store_id,
        )
    )
    alias = result.scalar_one_or_none()
    if alias is None:
        raise HTTPException(status_code=404, detail="Salesperson alias not found")
    await db.delete(alias)