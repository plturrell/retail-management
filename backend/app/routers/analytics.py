"""AI-powered analytics endpoints — margin analysis, forecasting, insights."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import UserStoreRole, User, UserStoreRole as USR
from app.models.order import Order, OrderItem, OrderStatus
from app.models.store import Store
from app.auth.dependencies import require_store_access, get_current_user
from app.schemas.common import DataResponse
from app.services.ai_analytics import (
    AnalyticsReport,
    compute_demand_forecasts,
    compute_margin_analysis,
    compute_sales_trends,
    generate_gemini_summary,
    generate_insights,
)
from app.services.inventory_logic import reorder_recommendations

router = APIRouter(prefix="/api/stores/{store_id}/analytics", tags=["analytics"])


class ReorderRecommendation(BaseModel):
    sku_id: str
    sku_code: str
    description: str
    qty_on_hand: int
    reorder_level: int
    avg_daily_sales: float
    days_until_stockout: Optional[float]
    recommended_order_qty: int
    urgency: str


@router.get("/report", response_model=AnalyticsReport)
async def full_analytics_report(
    store_id: UUID,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    include_gemini: bool = Query(False, description="Include Gemini AI summary"),
    _: UserStoreRole = Depends(require_store_access),
    db: AsyncSession = Depends(get_db),
):
    """Full analytics report: margins, trends, forecasts, AI insights."""
    margins = await compute_margin_analysis(db, store_id, from_date, to_date)
    trends = await compute_sales_trends(db, store_id, from_date, to_date)
    forecasts = await compute_demand_forecasts(db, store_id)
    insights = await generate_insights(db, store_id, margins, trends, forecasts)

    gemini_summary = None
    if include_gemini:
        report_data = {
            "store_id": str(store_id),
            "period": f"{from_date} to {to_date}",
            "top_margins": [m.model_dump() for m in margins[:10]],
            "recent_trends": [t.model_dump() for t in trends[-4:]],
            "forecasts": [f.model_dump() for f in forecasts[:10]],
            "insights": [i.model_dump() for i in insights],
        }
        gemini_summary = await generate_gemini_summary(report_data, store_id=store_id)

    return AnalyticsReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        store_id=str(store_id),
        period_from=str(from_date),
        period_to=str(to_date),
        margin_analysis=margins,
        sales_trends=trends,
        demand_forecasts=forecasts,
        ai_insights=insights,
        gemini_summary=gemini_summary,
    )


@router.get("/margins")
async def margin_analysis(
    store_id: UUID,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    _: UserStoreRole = Depends(require_store_access),
    db: AsyncSession = Depends(get_db),
):
    """Profitability analysis per SKU."""
    return await compute_margin_analysis(db, store_id, from_date, to_date)


@router.get("/forecasts")
async def demand_forecast(
    store_id: UUID,
    lookback_days: int = Query(60, ge=7, le=365),
    top_n: int = Query(20, ge=1, le=100),
    _: UserStoreRole = Depends(require_store_access),
    db: AsyncSession = Depends(get_db),
):
    """Demand forecasting per SKU based on sales velocity trends."""
    return await compute_demand_forecasts(db, store_id, lookback_days, top_n)


@router.get("/reorder", response_model=list[ReorderRecommendation])
async def reorder_suggestions(
    store_id: UUID,
    lookback_days: int = Query(30, ge=7, le=180),
    _: UserStoreRole = Depends(require_store_access),
    db: AsyncSession = Depends(get_db),
):
    """Intelligent reorder recommendations based on sales velocity and stock levels."""
    recs = await reorder_recommendations(db, store_id, lookback_days)
    return [ReorderRecommendation(**r) for r in recs]


# ------------------------------------------------------------------ #
# Staff performance helpers                                            #
# ------------------------------------------------------------------ #

async def _staff_performance_rows(db: AsyncSession, store_id: UUID, from_dt: datetime, to_dt: datetime) -> list[dict]:
    """Return list of {user_id, full_name, total_sales, order_count} sorted by total_sales desc."""
    query = (
        select(
            User.id,
            User.full_name,
            func.count(func.distinct(Order.id)).label("order_count"),
            func.coalesce(func.sum(Order.grand_total), 0).label("total_sales"),
        )
        .select_from(User)
        .join(USR, and_(USR.user_id == User.id, USR.store_id == store_id))
        .outerjoin(
            Order,
            and_(
                Order.staff_id == User.id,
                Order.store_id == store_id,
                Order.order_date >= from_dt,
                Order.order_date <= to_dt,
                Order.status != OrderStatus.voided,
            ),
        )
        .group_by(User.id, User.full_name)
        .order_by(func.coalesce(func.sum(Order.grand_total), 0).desc())
    )
    result = await db.execute(query)
    rows = result.all()
    return [
        {
            "userId": str(row[0]),
            "fullName": row[1] or "",
            "orderCount": int(row[2] or 0),
            "totalSales": float(row[3] or 0),
        }
        for row in rows
    ]


# ------------------------------------------------------------------ #
# GET /staff-performance                                               #
# ------------------------------------------------------------------ #

@router.get("/staff-performance", response_model=DataResponse)
async def staff_performance(
    store_id: UUID,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    _: UserStoreRole = Depends(require_store_access),
    db: AsyncSession = Depends(get_db),
):
    """Ranked staff performance for a date range."""
    from_dt = datetime.combine(from_date, datetime.min.time())
    to_dt = datetime.combine(to_date, datetime.max.time())

    rows = await _staff_performance_rows(db, store_id, from_dt, to_dt)

    staff_list = []
    for rank, row in enumerate(rows, start=1):
        avg = row["totalSales"] / row["orderCount"] if row["orderCount"] > 0 else 0.0
        staff_list.append({
            "userId": row["userId"],
            "fullName": row["fullName"],
            "totalSales": round(row["totalSales"], 2),
            "orderCount": row["orderCount"],
            "avgOrderValue": round(avg, 2),
            "rank": rank,
        })

    return DataResponse(
        success=True,
        message="Staff performance",
        data={
            "period": f"{from_date} to {to_date}",
            "totalStaff": len(staff_list),
            "staff": staff_list,
        },
    )


# ------------------------------------------------------------------ #
# GET /staff/{user_id}/insights                                        #
# ------------------------------------------------------------------ #

@router.get("/staff/{user_id}/insights", response_model=DataResponse)
async def staff_insights(
    store_id: UUID,
    user_id: UUID,
    _: UserStoreRole = Depends(require_store_access),
    db: AsyncSession = Depends(get_db),
):
    """AI-generated coaching insights for a single staff member (last 90 days)."""
    from app.services.ai_gateway import invoke, AIRequest

    to_dt = datetime.now(timezone.utc).replace(tzinfo=None)
    from_dt = to_dt - timedelta(days=90)
    from_date = from_dt.date()
    to_date = to_dt.date()

    # Fetch this user's performance
    rows = await _staff_performance_rows(db, store_id, from_dt, to_dt)
    user_row = next((r for r in rows if r["userId"] == str(user_id)), None)

    # Get user's full name
    u_q = await db.execute(select(User).where(User.id == user_id))
    user = u_q.scalar_one_or_none()
    full_name = user.full_name if user else "this staff member"

    # Get store name
    s_q = await db.execute(select(Store).where(Store.id == store_id))
    store = s_q.scalar_one_or_none()
    store_name = store.name if store else "the store"

    total_sales = round(user_row["totalSales"], 2) if user_row else 0.0
    order_count = user_row["orderCount"] if user_row else 0
    avg_order_value = round(total_sales / order_count, 2) if order_count > 0 else 0.0
    rank = next((i + 1 for i, r in enumerate(rows) if r["userId"] == str(user_id)), len(rows))
    total_staff = len(rows)

    prompt = (
        f"You are a retail performance coach. Here is a sales summary for {full_name} at {store_name}:\n"
        f"- Period: {from_date} to {to_date} (last 90 days)\n"
        f"- Total sales: SGD {total_sales:,.2f}\n"
        f"- Orders processed: {order_count}\n"
        f"- Average order value: SGD {avg_order_value:,.2f}\n"
        f"- Rank among {total_staff} staff: #{rank}\n\n"
        "Give 2-3 specific, actionable coaching insights in 150 words or less. "
        "Be direct, encouraging, and focused on what they can do differently this week."
    )

    resp = await invoke(
        AIRequest(prompt=prompt, purpose="staff_insights", timeout_seconds=12),
        fallback_text="Keep up the great work! Focus on upselling and building customer relationships.",
    )

    sales_summary = {
        "userId": str(user_id),
        "fullName": full_name,
        "totalSales": total_sales,
        "orderCount": order_count,
    }

    return DataResponse(
        success=True,
        message="Staff insights",
        data={
            "userId": str(user_id),
            "fullName": full_name,
            "aiInsights": resp.text,
            "salesSummary": sales_summary,
        },
    )
