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

from app.firestore_helpers import get_document, query_collection

logger = logging.getLogger(__name__)


def _coerce_order_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _load_store_orders(store_id: UUID) -> list[dict]:
    return query_collection(f"stores/{store_id}/orders")


def _filter_orders_for_period(
    orders: list[dict],
    start: date,
    end: date,
    *,
    salesperson_id: UUID | None = None,
) -> list[dict]:
    filtered: list[dict] = []
    salesperson_key = str(salesperson_id) if salesperson_id is not None else None
    for order in orders:
        if order.get("status") == "voided":
            continue
        if salesperson_key is not None and order.get("salesperson_id") != salesperson_key:
            continue
        order_date = _coerce_order_date(order.get("order_date"))
        if order_date is None or order_date < start or order_date > end:
            continue
        filtered.append(order)
    return filtered


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
    store_id: UUID,
    start_date: date,
    end_date: date,
) -> StaffPerformanceOverview:
    """Per-staff sales totals and ranking for a given period."""
    orders = [
        order for order in _filter_orders_for_period(
            _load_store_orders(store_id),
            start_date,
            end_date,
        )
        if order.get("salesperson_id")
    ]

    # Aggregate by salesperson
    sp_agg: dict[str, dict] = {}
    for o in orders:
        sp_id = o.get("salesperson_id", "")
        if sp_id not in sp_agg:
            sp_agg[sp_id] = {"total_sales": 0.0, "order_count": 0}
        sp_agg[sp_id]["total_sales"] += float(o.get("grand_total", 0))
        sp_agg[sp_id]["order_count"] += 1

    # Sort by total sales desc
    sorted_sp = sorted(sp_agg.items(), key=lambda x: x[1]["total_sales"], reverse=True)

    # Resolve user names
    name_map: dict[str, str] = {}
    for sp_id, _ in sorted_sp:
        user_doc = get_document("users", sp_id)
        if user_doc:
            name_map[sp_id] = user_doc.get("full_name", "Unknown")

    staff_items = []
    total_store_sales = 0.0
    for rank, (sp_id, agg) in enumerate(sorted_sp, start=1):
        total = agg["total_sales"]
        count = agg["order_count"]
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
    store_id: UUID, user_id: UUID,
    start: date, end: date,
) -> dict:
    """Get sales stats for a user in a given period."""
    orders = _filter_orders_for_period(
        _load_store_orders(store_id),
        start,
        end,
        salesperson_id=user_id,
    )
    total = sum(float(o.get("grand_total", 0)) for o in orders)
    count = len(orders)
    avg = total / count if count > 0 else 0.0
    return {
        "period_from": str(start),
        "period_to": str(end),
        "total_sales": round(total, 2),
        "order_count": count,
        "avg_order_value": round(avg, 2),
    }


async def get_staff_performance_comparison(
    store_id: UUID,
    user_id: UUID,
    current_start: date,
    current_end: date,
    previous_start: date,
    previous_end: date,
) -> PeriodComparison:
    """Compare a staff member's performance between two periods."""
    user_doc = get_document("users", str(user_id))
    full_name = user_doc.get("full_name", "Unknown") if user_doc else "Unknown"

    current = await _get_period_stats(store_id, user_id, current_start, current_end)
    previous = await _get_period_stats(store_id, user_id, previous_start, previous_end)

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
    store_id: UUID,
    user_id: UUID,
) -> StaffInsightsResponse:
    """Generate AI-powered insights for a specific staff member using Gemini."""
    from app.services.ai_gateway import AIRequest, SYNC_TIMEOUT_SECONDS, invoke

    # Get user name
    user_doc = get_document("users", str(user_id))
    full_name = user_doc.get("full_name", "Unknown") if user_doc else "Unknown"

    # Get last 30 days of sales data
    now = datetime.now(timezone.utc)
    thirty_days_ago = (now - timedelta(days=30)).date()
    today = now.date()

    summary = await _get_period_stats(store_id, user_id, thirty_days_ago, today)

    # Get daily breakdown for patterns from orders
    orders = sorted(
        _filter_orders_for_period(
            _load_store_orders(store_id),
            thirty_days_ago,
            today,
            salesperson_id=user_id,
        ),
        key=lambda order: _coerce_order_date(order.get("order_date")) or date.min,
    )

    daily_buckets: dict[str, dict] = {}
    for o in orders:
        od = o.get("order_date", "")
        day = od[:10] if isinstance(od, str) else str(od.date()) if hasattr(od, "date") else str(od)
        if day not in daily_buckets:
            daily_buckets[day] = {"sales": 0.0, "orders": 0}
        daily_buckets[day]["sales"] += float(o.get("grand_total", 0))
        daily_buckets[day]["orders"] += 1

    daily_data = [
        {"date": day, "sales": round(info["sales"], 2), "orders": info["orders"]}
        for day, info in sorted(daily_buckets.items())
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
    store_id: UUID,
) -> SchedulingRecommendationsResponse:
    """Suggest optimal staffing by day-of-week based on sales patterns."""
    from app.services.ai_gateway import AIRequest, SYNC_TIMEOUT_SECONDS, invoke

    # Get last 90 days of orders
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=90)

    orders = query_collection(
        f"stores/{store_id}/orders",
        filters=[("order_date", ">=", cutoff.date().isoformat())],
    )
    orders = [o for o in orders if o.get("status") != "voided"]

    # Build day-of-week breakdown (client-side aggregation)
    dow_data: dict[int, dict] = {}
    weeks_in_range = 13  # ~90 days
    for o in orders:
        od = o.get("order_date", "")
        if isinstance(od, str):
            order_date = date.fromisoformat(od[:10])
        else:
            order_date = od.date() if hasattr(od, "date") else od
        dow = order_date.weekday()  # 0=Monday ... 6=Sunday
        # Convert to strftime %w convention: 0=Sunday, 1=Monday...6=Saturday
        dow_key = (dow + 1) % 7
        if dow_key not in dow_data:
            dow_data[dow_key] = {"total_sales": 0.0, "total_orders": 0}
        dow_data[dow_key]["total_sales"] += float(o.get("grand_total", 0))
        dow_data[dow_key]["total_orders"] += 1

    for key in dow_data:
        d = dow_data[key]
        d["avg_weekly_sales"] = round(d["total_sales"] / weeks_in_range, 2)
        d["avg_weekly_orders"] = round(d["total_orders"] / weeks_in_range, 1)
        d["total_sales"] = round(d["total_sales"], 2)

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
