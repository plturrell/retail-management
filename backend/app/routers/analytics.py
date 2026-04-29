"""AI-powered analytics endpoints — margin analysis, forecasting, insights."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from app.auth.dependencies import ROLE_HIERARCHY, RoleEnum, get_current_user, require_store_access
from app.services.ai_analytics import (
    AnalyticsReport,
    compute_demand_forecasts,
    compute_margin_analysis,
    compute_sales_trends,
    generate_gemini_summary,
    generate_insights,
)
from app.services.inventory_logic import reorder_recommendations
from app.services.staff_analytics import (
    StaffPerformanceOverview,
    StaffInsightsResponse,
    SchedulingRecommendationsResponse,
    get_staff_sales_summary,
    generate_staff_insights,
    get_scheduling_recommendations,
)

router = APIRouter(prefix="/api/stores/{store_id}/analytics", tags=["analytics"])


def _role_name(role_assignment: dict) -> RoleEnum:
    raw_role = role_assignment.get("role")
    return raw_role if isinstance(raw_role, RoleEnum) else RoleEnum(str(raw_role))


def _is_manager_or_above(role_assignment: dict) -> bool:
    return ROLE_HIERARCHY[_role_name(role_assignment)] >= ROLE_HIERARCHY[RoleEnum.manager]


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
    _: dict = Depends(require_store_access),
):
    """Full analytics report: margins, trends, forecasts, AI insights."""
    margins = await compute_margin_analysis(store_id, from_date, to_date)
    trends = await compute_sales_trends(store_id, from_date, to_date)
    forecasts = await compute_demand_forecasts(store_id)
    insights = await generate_insights(store_id, margins, trends, forecasts)

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
    _: dict = Depends(require_store_access),
):
    """Profitability analysis per SKU."""
    return await compute_margin_analysis(store_id, from_date, to_date)


@router.get("/forecasts")
async def demand_forecast(
    store_id: UUID,
    lookback_days: int = Query(60, ge=7, le=365),
    top_n: int = Query(20, ge=1, le=100),
    _: dict = Depends(require_store_access),
):
    """Demand forecasting per SKU based on sales velocity trends."""
    return await compute_demand_forecasts(store_id, lookback_days, top_n)


@router.get("/reorder", response_model=list[ReorderRecommendation])
async def reorder_suggestions(
    store_id: UUID,
    lookback_days: int = Query(30, ge=7, le=180),
    _: dict = Depends(require_store_access),
):
    """Intelligent reorder recommendations based on sales velocity and stock levels."""
    recs = await reorder_recommendations(store_id, lookback_days)
    return [ReorderRecommendation(**r) for r in recs]



# ──────────────────── Staff Performance ──────────────────


@router.get("/staff-performance", response_model=StaffPerformanceOverview)
async def staff_performance(
    store_id: UUID,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    role_assignment: dict = Depends(require_store_access),
    user: dict = Depends(get_current_user),
):
    """Staff performance overview.

    Managers and owners can see the full team. Staff users only receive their
    own row, so clients cannot reveal peer names or sales by bypassing UI masks.
    """
    overview = await get_staff_sales_summary(store_id, from_date, to_date)
    if _is_manager_or_above(role_assignment):
        return overview

    user_id = str(user.get("id"))
    own_rows = [row for row in overview.staff if row.user_id == user_id]
    return overview.model_copy(
        update={
            "staff": own_rows,
            "total_store_sales": round(sum(row.total_sales for row in own_rows), 2),
        }
    )


@router.get("/staff/{user_id}/insights", response_model=StaffInsightsResponse)
async def staff_insights(
    store_id: UUID,
    user_id: UUID,
    role_assignment: dict = Depends(require_store_access),
    user: dict = Depends(get_current_user),
):
    """AI-generated insights for an individual staff member."""
    if str(user.get("id")) != str(user_id) and not _is_manager_or_above(role_assignment):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own staff insights",
        )
    return await generate_staff_insights(store_id, user_id)


@router.get("/scheduling-recommendations", response_model=SchedulingRecommendationsResponse)
async def scheduling_recommendations(
    store_id: UUID,
    _: dict = Depends(require_store_access),
):
    """AI-powered scheduling recommendations based on sales patterns."""
    return await get_scheduling_recommendations(store_id)
