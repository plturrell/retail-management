from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from google.cloud.firestore_v1.client import Client as FirestoreClient

from app.firestore import get_firestore_db
from app.firestore_helpers import (
    create_document,
    delete_document,
    get_document,
    query_collection,
)
from app.auth.dependencies import ROLE_HIERARCHY, RoleEnum, get_current_user, require_store_access, require_store_role
from app.schemas.common import DataResponse
from app.schemas.order import (
    SalespersonAliasCreate,
    SalespersonAliasRead,
    StaffSalesSummary,
)

router = APIRouter(prefix="/api/stores/{store_id}/sales", tags=["sales"])


def _orders_col(store_id: UUID) -> str:
    return f"stores/{store_id}/orders"


def _alias_col(store_id: UUID) -> str:
    return f"stores/{store_id}/salesperson-aliases"


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


def _get_non_voided_orders(store_id: UUID, range_start: datetime, range_end: datetime) -> list[dict]:
    """Fetch orders from Firestore within a date range, excluding voided."""
    orders = query_collection(
        _orders_col(store_id),
        filters=[
            ("order_date", ">=", range_start),
            ("order_date", "<=", range_end),
        ],
    )
    return [o for o in orders if o.get("status") != "voided"]


@router.get("/daily", response_model=DailySalesSummary)
async def daily_sales(
    store_id: UUID,
    date: date = Query(..., alias="date"),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Daily summary: total sales, order count, avg order value, breakdown by payment method."""
    day_start = datetime.combine(date, datetime.min.time())
    day_end = datetime.combine(date, datetime.max.time())

    orders = _get_non_voided_orders(store_id, day_start, day_end)

    total_sales = sum(float(o.get("grand_total", 0)) for o in orders)
    order_count = len(orders)
    avg_order_value = total_sales / order_count if order_count > 0 else 0.0

    pm_map: dict[str, dict] = {}
    for o in orders:
        pm = o.get("payment_method", "unknown")
        if pm not in pm_map:
            pm_map[pm] = {"total": 0.0, "count": 0}
        pm_map[pm]["total"] += float(o.get("grand_total", 0))
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
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Date range summary with daily breakdown."""
    range_start = datetime.combine(from_date, datetime.min.time())
    range_end = datetime.combine(to_date, datetime.max.time())

    orders = _get_non_voided_orders(store_id, range_start, range_end)

    total_sales = sum(float(o.get("grand_total", 0)) for o in orders)
    order_count = len(orders)
    avg_order_value = total_sales / order_count if order_count > 0 else 0.0

    # Build daily breakdown
    daily_map: dict[str, list] = {}
    for o in orders:
        od = o.get("order_date")
        if hasattr(od, "date"):
            day_key = od.date().isoformat()
        else:
            day_key = str(od)[:10]
        if day_key not in daily_map:
            daily_map[day_key] = []
        daily_map[day_key].append(o)

    daily_summaries = []
    current = from_date
    while current <= to_date:
        day_key = current.isoformat()
        day_orders = daily_map.get(day_key, [])
        day_total = sum(float(o.get("grand_total", 0)) for o in day_orders)
        day_count = len(day_orders)
        day_avg = day_total / day_count if day_count > 0 else 0.0

        pm_map: dict[str, dict] = {}
        for o in day_orders:
            pm = o.get("payment_method", "unknown")
            if pm not in pm_map:
                pm_map[pm] = {"total": 0.0, "count": 0}
            pm_map[pm]["total"] += float(o.get("grand_total", 0))
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
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Sales grouped by category for a date range (client-side aggregation)."""
    range_start = datetime.combine(from_date, datetime.min.time())
    range_end = datetime.combine(to_date, datetime.max.time())

    orders = _get_non_voided_orders(store_id, range_start, range_end)

    # Build SKU lookup for category_id
    sku_col = f"stores/{store_id}/inventory"
    all_skus = query_collection(sku_col)
    sku_map = {s["id"]: s for s in all_skus}

    # Build category lookup
    cat_col = f"stores/{store_id}/categories"
    all_cats = query_collection(cat_col)
    cat_map = {c["id"]: c.get("description", "Uncategorized") for c in all_cats}

    # Aggregate
    cat_agg: dict[str, dict] = {}  # category_id -> {total_sales, qty_sold}
    for order in orders:
        for item in order.get("items", []):
            sku_id = item.get("sku_id", "")
            sku = sku_map.get(sku_id, {})
            cat_id = sku.get("category_id")
            key = cat_id or "__none__"
            if key not in cat_agg:
                cat_agg[key] = {"total_sales": 0.0, "qty_sold": 0}
            cat_agg[key]["total_sales"] += float(item.get("line_total", 0))
            cat_agg[key]["qty_sold"] += int(item.get("qty", 0))

    return [
        CategorySales(
            category_id=k if k != "__none__" else None,
            category_name=cat_map.get(k, "Uncategorized") if k != "__none__" else "Uncategorized",
            total_sales=round(v["total_sales"], 2),
            qty_sold=v["qty_sold"],
        )
        for k, v in cat_agg.items()
    ]


@router.get("/by-brand", response_model=list[BrandSales])
async def sales_by_brand(
    store_id: UUID,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Sales grouped by brand for a date range (client-side aggregation)."""
    range_start = datetime.combine(from_date, datetime.min.time())
    range_end = datetime.combine(to_date, datetime.max.time())

    orders = _get_non_voided_orders(store_id, range_start, range_end)

    # Build SKU lookup for brand_id
    sku_col = f"stores/{store_id}/inventory"
    all_skus = query_collection(sku_col)
    sku_map = {s["id"]: s for s in all_skus}

    # Build brand lookup
    all_brands = query_collection("brands")
    brand_map = {b["id"]: b.get("name", "Unbranded") for b in all_brands}

    # Aggregate
    brand_agg: dict[str, dict] = {}
    for order in orders:
        for item in order.get("items", []):
            sku_id = item.get("sku_id", "")
            sku = sku_map.get(sku_id, {})
            brand_id = sku.get("brand_id")
            key = brand_id or "__none__"
            if key not in brand_agg:
                brand_agg[key] = {"total_sales": 0.0, "qty_sold": 0}
            brand_agg[key]["total_sales"] += float(item.get("line_total", 0))
            brand_agg[key]["qty_sold"] += int(item.get("qty", 0))

    return [
        BrandSales(
            brand_id=k if k != "__none__" else None,
            brand_name=brand_map.get(k, "Unbranded") if k != "__none__" else "Unbranded",
            total_sales=round(v["total_sales"], 2),
            qty_sold=v["qty_sold"],
        )
        for k, v in brand_agg.items()
    ]


# ─── Sales by Staff ────────────────────────────────────────────────


@router.get("/by-staff", response_model=DataResponse[list[StaffSalesSummary]])
async def sales_by_staff(
    store_id: UUID,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    user: dict = Depends(get_current_user),
    role_assignment: dict = Depends(require_store_access),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Sales grouped by salesperson_id with totals for a date range.

    Managers and owners can see the full team. Staff users only receive their
    own row.
    """
    range_start = datetime.combine(from_date, datetime.min.time())
    range_end = datetime.combine(to_date, datetime.max.time())

    orders = _get_non_voided_orders(store_id, range_start, range_end)

    # Client-side group by salesperson_id
    sp_agg: dict[str, dict] = {}
    for o in orders:
        sp_id = o.get("salesperson_id")
        key = sp_id or "__none__"
        if key not in sp_agg:
            sp_agg[key] = {"total_sales": 0.0, "order_count": 0}
        sp_agg[key]["total_sales"] += float(o.get("grand_total", 0))
        sp_agg[key]["order_count"] += 1

    # Build user name lookup from Firestore
    from app.firestore_helpers import get_document as gd
    name_map: dict[str, str] = {}
    for sp_id in sp_agg:
        if sp_id != "__none__":
            user_doc = gd("users", sp_id)
            if user_doc:
                name_map[sp_id] = user_doc.get("full_name", "")

    summaries = []
    raw_role = role_assignment.get("role")
    role_name = raw_role if isinstance(raw_role, RoleEnum) else RoleEnum(str(raw_role))
    can_view_team = ROLE_HIERARCHY[role_name] >= ROLE_HIERARCHY[RoleEnum.manager]
    current_user_id = str(user.get("id"))

    for sp_id, agg in sp_agg.items():
        if not can_view_team and sp_id != current_user_id:
            continue
        total = agg["total_sales"]
        count = agg["order_count"]
        avg = total / count if count > 0 else 0.0
        summaries.append(
            StaffSalesSummary(
                salesperson_id=UUID(sp_id) if sp_id != "__none__" else None,
                salesperson_name=name_map.get(sp_id) if sp_id != "__none__" else None,
                total_sales=round(total, 2),
                order_count=count,
                avg_order_value=round(avg, 2),
            )
        )

    return DataResponse(data=summaries)


# ─── Salesperson Aliases CRUD ──────────────────────────────────────


def _alias_to_read(data: dict) -> SalespersonAliasRead:
    return SalespersonAliasRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        alias_name=data.get("alias_name", ""),
        user_id=UUID(data["user_id"]) if isinstance(data.get("user_id"), str) else data.get("user_id"),
        store_id=UUID(data["store_id"]) if isinstance(data.get("store_id"), str) else data.get("store_id"),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
    )


@router.post(
    "/salesperson-aliases",
    response_model=DataResponse[SalespersonAliasRead],
    status_code=201,
)
async def create_salesperson_alias(
    store_id: UUID,
    payload: SalespersonAliasCreate,
    _=Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Create a salesperson alias for OCR name matching."""
    now = datetime.now(timezone.utc)
    doc_id = str(_uuid.uuid4())
    doc_data = {
        "alias_name": payload.alias_name,
        "user_id": str(payload.user_id),
        "store_id": str(store_id),
        "created_at": now,
    }
    created = create_document(_alias_col(store_id), doc_data, doc_id=doc_id)
    return DataResponse(data=_alias_to_read(created))


@router.get(
    "/salesperson-aliases",
    response_model=DataResponse[list[SalespersonAliasRead]],
)
async def list_salesperson_aliases(
    store_id: UUID,
    _=Depends(require_store_role(RoleEnum.staff)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """List all salesperson aliases for a store."""
    aliases = query_collection(_alias_col(store_id))
    return DataResponse(data=[_alias_to_read(a) for a in aliases])


@router.delete("/salesperson-aliases/{alias_id}", status_code=204)
async def delete_salesperson_alias(
    store_id: UUID,
    alias_id: UUID,
    _=Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Delete a salesperson alias."""
    data = get_document(_alias_col(store_id), str(alias_id))
    if data is None:
        raise HTTPException(status_code=404, detail="Salesperson alias not found")
    delete_document(_alias_col(store_id), str(alias_id))
