"""Staff performance analytics — per-staff sales analysis and AI insights.

Provides:
  - Per-staff sales totals with ranking
  - Period-over-period performance comparison
  - AI-generated staff insights via Gemini
  - Scheduling recommendations based on sales patterns
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select, extract
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderStatus
from app.models.user import User, UserStoreRole, RoleEnum
from app.models.timesheet import TimeEntry

logger = logging.getLogger(__name__)


# ──────────────────── Response Models ────────────────────


class StaffPerformanceItem(BaseModel):
    user_id: str
    full_name: str
    total_sales: float
    order_count: int
    avg_order_value: float
    rank: int


class StaffPerformanceOverview(BaseModel):
    generated_at: str
    store_id: str
    period_from: str
    period_to: str
    staff: list[StaffPerformanceItem]
    total_store_sales: float


class PeriodComparison(BaseModel):
    user_id: str
    full_name: str
    current_period: dict
    previous_period: dict
    change_pct: Optional[float]


class StaffInsightsResponse(BaseModel):
    user_id: str
    full_name: str
    summary: dict
    ai_insights: Optional[str] = None


class DayRecommendation(BaseModel):
    day_of_week: str
    avg_sales: float
    recommended_staff_count: int
    reasoning: str


class SchedulingRecommendationsResponse(BaseModel):
    store_id: str
    generated_at: str
    recommendations: list[DayRecommendation]
    ai_summary: Optional[str] = None


# ──────────────────── Staff Sales Summary ────────────────


async def get_staff_sales_summary(
    db: AsyncSession,
    store_id: UUID,
    start_date: date,
    end_date: date,
) -> StaffPerformanceOverview:
    """Per-staff sales totals and ranking for a given period."""
    range_start = datetime.combine(start_date, datetime.min.time())
    range_end = datetime.combine(end_date, datetime.max.time())

    query = (
        select(
            Order.salesperson_id,
            func.sum(Order.grand_total).label("total_sales"),
            func.count(Order.id).label("order_count"),
        )
        .where(
            Order.store_id == store_id,
            Order.status != OrderStatus.voided,
            Order.order_date >= range_start,
            Order.order_date <= range_end,
            Order.salesperson_id.isnot(None),
        )
        .group_by(Order.salesperson_id)
        .order_by(func.sum(Order.grand_total).desc())
    )
    result = await db.execute(query)
    rows = result.all()

    # Resolve user names
    sp_ids = [row[0] for row in rows]
    name_map: dict[UUID, str] = {}
    if sp_ids:
        user_result = await db.execute(
            select(User.id, User.full_name).where(User.id.in_(sp_ids))
        )
        name_map = {uid: name for uid, name in user_result.all()}

    staff_items = []
    total_store_sales = 0.0
    for rank, (sp_id, total_sales, order_count) in enumerate(rows, start=1):
        total = float(total_sales or 0)
        count = int(order_count or 0)
        avg = total / count if count > 0 else 0.0
        total_store_sales += total
        staff_items.append(StaffPerformanceItem(
            user_id=str(sp_id),
            full_name=name_map.get(sp_id, "Unknown"),
            total_sales=round(total, 2),
            order_count=count,
            avg_order_value=round(avg, 2),
            rank=rank,
        ))

    return StaffPerformanceOverview(
        generated_at=datetime.now(timezone.utc).isoformat(),
        store_id=str(store_id),
        period_from=str(start_date),
        period_to=str(end_date),
        staff=staff_items,
        total_store_sales=round(total_store_sales, 2),
    )


# ──────────────────── Performance Comparison ─────────────


async def _get_period_stats(
    db: AsyncSession, store_id: UUID, user_id: UUID,
    start: date, end: date,
) -> dict:
    """Get sales stats for a user in a given period."""
    range_start = datetime.combine(start, datetime.min.time())
    range_end = datetime.combine(end, datetime.max.time())

    query = (
        select(
            func.sum(Order.grand_total).label("total_sales"),
            func.count(Order.id).label("order_count"),
        )
        .where(
            Order.store_id == store_id,
            Order.salesperson_id == user_id,
            Order.status != OrderStatus.voided,
            Order.order_date >= range_start,
            Order.order_date <= range_end,
        )
    )
    result = await db.execute(query)
    row = result.one()
    total = float(row[0] or 0)
    count = int(row[1] or 0)
    avg = total / count if count > 0 else 0.0
    return {
        "period_from": str(start),
        "period_to": str(end),
        "total_sales": round(total, 2),
        "order_count": count,
        "avg_order_value": round(avg, 2),
    }


async def get_staff_performance_comparison(
    db: AsyncSession,
    store_id: UUID,
    user_id: UUID,
    current_start: date,
    current_end: date,
    previous_start: date,
    previous_end: date,
) -> PeriodComparison:
    """Compare a staff member's performance between two periods."""
    user_result = await db.execute(
        select(User.full_name).where(User.id == user_id)
    )
    full_name = user_result.scalar_one_or_none() or "Unknown"

    current = await _get_period_stats(db, store_id, user_id, current_start, current_end)
    previous = await _get_period_stats(db, store_id, user_id, previous_start, previous_end)

    change_pct = None
    if previous["total_sales"] > 0:
        change_pct = round(
            (current["total_sales"] - previous["total_sales"]) / previous["total_sales"] * 100, 1
        )

    return PeriodComparison(
        user_id=str(user_id),
        full_name=full_name,
        current_period=current,
        previous_period=previous,
        change_pct=change_pct,
    )


# ──────────────────── AI Staff Insights ──────────────────


async def generate_staff_insights(
    db: AsyncSession,
    store_id: UUID,
    user_id: UUID,
) -> StaffInsightsResponse:
    """Generate AI-powered insights for a specific staff member using Gemini."""
    from app.services.ai_gateway import AIRequest, SYNC_TIMEOUT_SECONDS, invoke

    # Get user name
    user_result = await db.execute(
        select(User.full_name).where(User.id == user_id)
    )
    full_name = user_result.scalar_one_or_none() or "Unknown"

    # Get last 30 days of sales data
    now = datetime.now(timezone.utc)
    thirty_days_ago = (now - timedelta(days=30)).date()
    today = now.date()

    summary = await _get_period_stats(db, store_id, user_id, thirty_days_ago, today)

    # Get daily breakdown for patterns
    range_start = datetime.combine(thirty_days_ago, datetime.min.time())
    range_end = datetime.combine(today, datetime.max.time())

    daily_query = (
        select(
            func.date(Order.order_date).label("day"),
            func.sum(Order.grand_total).label("daily_total"),
            func.count(Order.id).label("daily_count"),
        )
        .where(
            Order.store_id == store_id,
            Order.salesperson_id == user_id,
            Order.status != OrderStatus.voided,
            Order.order_date >= range_start,
            Order.order_date <= range_end,
        )
        .group_by(func.date(Order.order_date))
        .order_by(func.date(Order.order_date))
    )
    daily_result = await db.execute(daily_query)
    daily_rows = daily_result.all()
    daily_data = [
        {"date": str(row[0]), "sales": float(row[1] or 0), "orders": int(row[2] or 0)}
        for row in daily_rows
    ]

    # Build prompt for Gemini
    prompt_data = {
        "staff_name": full_name,
        "period": f"{thirty_days_ago} to {today}",
        "summary": summary,
        "daily_breakdown": daily_data,
    }

    prompt = f"""You are a retail performance analyst for a Singapore jewelry store.
Analyze this staff member's sales performance and provide actionable insights.
Focus on: sales patterns, peak performance days, areas for improvement,
and specific coaching recommendations.

STAFF DATA:
{json.dumps(prompt_data, indent=2, default=str)[:6000]}

Respond in professional business English. Keep it concise (3-4 paragraphs).
No markdown formatting."""

    resp = await invoke(
        AIRequest(
            prompt=prompt,
            purpose="staff_insights",
            timeout_seconds=SYNC_TIMEOUT_SECONDS,
            max_output_tokens=1024,
            store_id=store_id,
        ),
        fallback_text="",
    )

    ai_text = resp.text.strip() if not resp.is_fallback and resp.text.strip() else None

    return StaffInsightsResponse(
        user_id=str(user_id),
        full_name=full_name,
        summary=summary,
        ai_insights=ai_text,
    )



# ──────────────────── Scheduling Recommendations ─────────


_DOW_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


async def get_scheduling_recommendations(
    db: AsyncSession,
    store_id: UUID,
) -> SchedulingRecommendationsResponse:
    """Suggest optimal staffing by day-of-week based on sales patterns."""
    from app.services.ai_gateway import AIRequest, SYNC_TIMEOUT_SECONDS, invoke

    # Get last 90 days of sales grouped by day-of-week
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=90)

    query = (
        select(
            func.strftime("%w", Order.order_date).label("dow"),
            func.sum(Order.grand_total).label("total_sales"),
            func.count(Order.id).label("order_count"),
        )
        .where(
            Order.store_id == store_id,
            Order.status != OrderStatus.voided,
            Order.order_date >= cutoff,
        )
        .group_by(func.strftime("%w", Order.order_date))
    )
    result = await db.execute(query)
    rows = result.all()

    # Build day-of-week breakdown
    dow_data: dict[int, dict] = {}
    weeks_in_range = 13  # ~90 days
    for row in rows:
        dow = int(row[0])  # 0=Sunday in strftime %w
        total = float(row[1] or 0)
        count = int(row[2] or 0)
        avg_sales = total / weeks_in_range
        dow_data[dow] = {
            "total_sales": round(total, 2),
            "avg_weekly_sales": round(avg_sales, 2),
            "total_orders": count,
            "avg_weekly_orders": round(count / weeks_in_range, 1),
        }

    # Build recommendations (rule-based first, then AI summary)
    recommendations = []
    max_avg = max((d["avg_weekly_sales"] for d in dow_data.values()), default=1)

    for i, day_name in enumerate(_DOW_NAMES):
        # strftime %w: 0=Sunday, 1=Monday, ..., 6=Saturday
        dow_key = (i + 1) % 7  # Convert Monday=0 → 1, Sunday=6 → 0
        data = dow_data.get(dow_key, {"avg_weekly_sales": 0, "avg_weekly_orders": 0})
        avg_sales = data.get("avg_weekly_sales", 0)

        # Simple staffing heuristic based on relative sales volume
        if max_avg > 0:
            ratio = avg_sales / max_avg
        else:
            ratio = 0
        if ratio >= 0.8:
            staff_count = 4
            reasoning = "Peak sales day — full staffing recommended"
        elif ratio >= 0.5:
            staff_count = 3
            reasoning = "Moderate sales volume — standard staffing"
        elif ratio >= 0.2:
            staff_count = 2
            reasoning = "Lower sales volume — reduced staffing sufficient"
        else:
            staff_count = 1
            reasoning = "Minimal sales — skeleton crew"

        recommendations.append(DayRecommendation(
            day_of_week=day_name,
            avg_sales=round(avg_sales, 2),
            recommended_staff_count=staff_count,
            reasoning=reasoning,
        ))

    # Generate AI summary
    prompt_data = {
        "store_id": str(store_id),
        "period": "Last 90 days",
        "day_of_week_data": {r.day_of_week: {"avg_sales": r.avg_sales, "staff": r.recommended_staff_count} for r in recommendations},
    }
    prompt = f"""You are a retail scheduling advisor for a Singapore jewelry store.
Based on this day-of-week sales data, provide a brief scheduling recommendation
(2-3 paragraphs). Focus on which days need more staff, when to schedule top
performers, and any patterns you notice.

DATA:
{json.dumps(prompt_data, indent=2, default=str)}

Respond in professional business English. No markdown formatting."""

    resp = await invoke(
        AIRequest(
            prompt=prompt,
            purpose="scheduling_recommendations",
            timeout_seconds=SYNC_TIMEOUT_SECONDS,
            max_output_tokens=512,
            store_id=store_id,
        ),
        fallback_text="",
    )
    ai_summary = resp.text.strip() if not resp.is_fallback and resp.text.strip() else None

    return SchedulingRecommendationsResponse(
        store_id=str(store_id),
        generated_at=datetime.now(timezone.utc).isoformat(),
        recommendations=recommendations,
        ai_summary=ai_summary,
    )