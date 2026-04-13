"""AI-powered analytics — uses Gemini for reasoning over real sales data.

Provides:
  - Sales trend analysis with natural-language insights
  - Demand forecasting per SKU
  - Profitability analysis (margin calculations)
  - Actionable recommendations
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import Inventory, Price, SKU, Category
from app.models.order import Order, OrderItem, OrderStatus

logger = logging.getLogger(__name__)


# ──────────────────── Response Models ────────────────────


class MarginItem(BaseModel):
    sku_id: str
    sku_code: str
    description: str
    cost_price: Optional[float]
    selling_price: Optional[float]
    margin_pct: Optional[float]
    total_sold: int
    total_revenue: float
    total_profit: float
    health: str  # "healthy", "thin", "negative"


class SalesTrend(BaseModel):
    period: str
    total_sales: float
    order_count: int
    avg_order_value: float


class DemandForecast(BaseModel):
    sku_id: str
    sku_code: str
    description: str
    avg_daily_sales: float
    trend: str  # "rising", "stable", "declining"
    forecast_next_7d: float
    forecast_next_30d: float


class AIInsight(BaseModel):
    category: str  # "revenue", "margin", "inventory", "trend"
    severity: str  # "info", "warning", "critical"
    title: str
    detail: str
    action: Optional[str] = None


class AnalyticsReport(BaseModel):
    generated_at: str
    store_id: str
    period_from: str
    period_to: str
    margin_analysis: list[MarginItem]
    sales_trends: list[SalesTrend]
    demand_forecasts: list[DemandForecast]
    ai_insights: list[AIInsight]
    gemini_summary: Optional[str] = None


# ──────────────────── Margin Analysis ────────────────────


async def compute_margin_analysis(
    db: AsyncSession,
    store_id: UUID,
    from_date: date,
    to_date: date,
) -> list[MarginItem]:
    """Calculate profit margins per SKU from actual sales data."""
    range_start = datetime.combine(from_date, datetime.min.time())
    range_end = datetime.combine(to_date, datetime.max.time())

    # Aggregate sales by SKU
    query = (
        select(
            OrderItem.sku_id,
            func.sum(OrderItem.qty).label("total_qty"),
            func.sum(OrderItem.line_total).label("total_revenue"),
        )
        .select_from(OrderItem)
        .join(Order, OrderItem.order_id == Order.id)
        .where(
            Order.store_id == store_id,
            Order.status != OrderStatus.voided,
            Order.order_date >= range_start,
            Order.order_date <= range_end,
        )
        .group_by(OrderItem.sku_id)
    )
    result = await db.execute(query)
    rows = result.all()

    items: list[MarginItem] = []
    for sku_id, total_qty, total_revenue in rows:
        sku_result = await db.execute(select(SKU).where(SKU.id == sku_id))
        sku = sku_result.scalar_one_or_none()
        if sku is None:
            continue

        cost = float(sku.cost_price) if sku.cost_price else None
        revenue = float(total_revenue or 0)
        qty = int(total_qty or 0)

        if cost and qty > 0:
            total_cost = cost * qty
            profit = revenue - total_cost
            margin_pct = round((profit / revenue) * 100, 1) if revenue > 0 else 0.0
            health = "healthy" if margin_pct >= 30 else "thin" if margin_pct >= 10 else "negative"
        else:
            profit = 0.0
            margin_pct = None
            health = "healthy"

        # Get current selling price
        price_result = await db.execute(
            select(Price.price_incl_tax)
            .where(Price.sku_id == sku_id, Price.store_id == store_id)
            .order_by(Price.valid_from.desc())
            .limit(1)
        )
        selling_price = price_result.scalar_one_or_none()

        items.append(MarginItem(
            sku_id=str(sku_id),
            sku_code=sku.sku_code,
            description=sku.description,
            cost_price=cost,
            selling_price=float(selling_price) if selling_price else None,
            margin_pct=margin_pct,
            total_sold=qty,
            total_revenue=round(revenue, 2),
            total_profit=round(profit, 2),
            health=health,
        ))

    # Sort by profit descending
    items.sort(key=lambda x: x.total_profit, reverse=True)
    return items


# ──────────────────── Sales Trends ───────────────────────


async def compute_sales_trends(
    db: AsyncSession,
    store_id: UUID,
    from_date: date,
    to_date: date,
    granularity: str = "weekly",
) -> list[SalesTrend]:
    """Aggregate sales into weekly or daily buckets for trend analysis."""
    range_start = datetime.combine(from_date, datetime.min.time())
    range_end = datetime.combine(to_date, datetime.max.time())

    result = await db.execute(
        select(Order).where(
            Order.store_id == store_id,
            Order.status != OrderStatus.voided,
            Order.order_date >= range_start,
            Order.order_date <= range_end,
        ).order_by(Order.order_date)
    )
    orders = result.scalars().all()

    if granularity == "daily":
        bucket_fn = lambda o: o.order_date.date().isoformat()
    else:
        # Weekly: group by ISO week start (Monday)
        bucket_fn = lambda o: (o.order_date.date() - timedelta(days=o.order_date.weekday())).isoformat()

    buckets: dict[str, list] = {}
    for o in orders:
        key = bucket_fn(o)
        buckets.setdefault(key, []).append(o)

    trends = []
    for period, period_orders in sorted(buckets.items()):
        total = sum(float(o.grand_total) for o in period_orders)
        count = len(period_orders)
        avg = total / count if count > 0 else 0.0
        trends.append(SalesTrend(
            period=period,
            total_sales=round(total, 2),
            order_count=count,
            avg_order_value=round(avg, 2),
        ))

    return trends


# ──────────────────── Demand Forecasting ─────────────────


async def compute_demand_forecasts(
    db: AsyncSession,
    store_id: UUID,
    lookback_days: int = 60,
    top_n: int = 20,
) -> list[DemandForecast]:
    """Simple linear trend-based demand forecast per SKU.

    Compares sales in the recent half vs older half of the lookback window
    to determine if demand is rising, stable, or declining.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)
    midpoint = now - timedelta(days=lookback_days // 2)

    # Top SKUs by volume
    top_query = (
        select(
            OrderItem.sku_id,
            func.sum(OrderItem.qty).label("total_qty"),
        )
        .select_from(OrderItem)
        .join(Order, OrderItem.order_id == Order.id)
        .where(
            Order.store_id == store_id,
            Order.status != OrderStatus.voided,
            Order.order_date >= cutoff,
        )
        .group_by(OrderItem.sku_id)
        .order_by(func.sum(OrderItem.qty).desc())
        .limit(top_n)
    )
    result = await db.execute(top_query)
    top_skus = result.all()

    forecasts = []
    for sku_id, total_qty in top_skus:
        total_qty = int(total_qty)
        avg_daily = total_qty / lookback_days

        # Split into two halves for trend
        older_q = (
            select(func.coalesce(func.sum(OrderItem.qty), 0))
            .select_from(OrderItem)
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                Order.store_id == store_id,
                Order.status != OrderStatus.voided,
                Order.order_date >= cutoff,
                Order.order_date < midpoint,
                OrderItem.sku_id == sku_id,
            )
        )
        newer_q = (
            select(func.coalesce(func.sum(OrderItem.qty), 0))
            .select_from(OrderItem)
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                Order.store_id == store_id,
                Order.status != OrderStatus.voided,
                Order.order_date >= midpoint,
                OrderItem.sku_id == sku_id,
            )
        )
        older_result = await db.execute(older_q)
        newer_result = await db.execute(newer_q)
        older_sales = int(older_result.scalar() or 0)
        newer_sales = int(newer_result.scalar() or 0)

        if older_sales > 0:
            change_pct = (newer_sales - older_sales) / older_sales
            trend = "rising" if change_pct > 0.15 else "declining" if change_pct < -0.15 else "stable"
            # Adjust forecast based on trend
            trend_multiplier = 1 + (change_pct * 0.5)  # dampen the trend
        else:
            trend = "stable"
            trend_multiplier = 1.0

        forecast_daily = avg_daily * trend_multiplier
        forecast_7d = round(forecast_daily * 7, 1)
        forecast_30d = round(forecast_daily * 30, 1)

        sku_result = await db.execute(select(SKU).where(SKU.id == sku_id))
        sku = sku_result.scalar_one_or_none()

        forecasts.append(DemandForecast(
            sku_id=str(sku_id),
            sku_code=sku.sku_code if sku else "UNKNOWN",
            description=sku.description if sku else "",
            avg_daily_sales=round(avg_daily, 2),
            trend=trend,
            forecast_next_7d=forecast_7d,
            forecast_next_30d=forecast_30d,
        ))

    return forecasts


# ──────────────────── Rule-Based Insights ────────────────


async def generate_insights(
    db: AsyncSession,
    store_id: UUID,
    margins: list[MarginItem],
    trends: list[SalesTrend],
    forecasts: list[DemandForecast],
) -> list[AIInsight]:
    """Generate actionable insights from computed analytics."""
    insights: list[AIInsight] = []

    # Margin insights
    negative_margins = [m for m in margins if m.margin_pct is not None and m.margin_pct < 10]
    if negative_margins:
        skus = ", ".join(m.sku_code for m in negative_margins[:5])
        insights.append(AIInsight(
            category="margin",
            severity="critical" if any(m.margin_pct < 0 for m in negative_margins) else "warning",
            title=f"{len(negative_margins)} SKUs with thin/negative margins",
            detail=f"Review pricing for: {skus}",
            action="Consider raising prices or renegotiating supplier costs",
        ))

    # Revenue trend
    if len(trends) >= 2:
        recent = trends[-1].total_sales
        previous = trends[-2].total_sales
        if previous > 0:
            change = (recent - previous) / previous * 100
            if change < -20:
                insights.append(AIInsight(
                    category="revenue",
                    severity="warning",
                    title=f"Sales declined {abs(change):.0f}% vs previous period",
                    detail=f"${previous:.0f} → ${recent:.0f}",
                    action="Review promotions, staffing, and marketing",
                ))
            elif change > 20:
                insights.append(AIInsight(
                    category="revenue",
                    severity="info",
                    title=f"Sales grew {change:.0f}% vs previous period",
                    detail=f"${previous:.0f} → ${recent:.0f}",
                    action="Ensure adequate inventory for sustained demand",
                ))

    # Demand forecasts — rising items
    rising = [f for f in forecasts if f.trend == "rising"]
    if rising:
        items = ", ".join(f.sku_code for f in rising[:3])
        insights.append(AIInsight(
            category="trend",
            severity="info",
            title=f"{len(rising)} SKUs with rising demand",
            detail=f"Top movers: {items}",
            action="Pre-order stock to avoid stockouts",
        ))

    declining = [f for f in forecasts if f.trend == "declining"]
    if declining:
        items = ", ".join(f.sku_code for f in declining[:3])
        insights.append(AIInsight(
            category="trend",
            severity="warning",
            title=f"{len(declining)} SKUs with declining demand",
            detail=f"Slowing: {items}",
            action="Consider markdowns or promotional bundles",
        ))

    # Inventory alerts (requires DB session)
    if db is not None and store_id is not None:
        inv_result = await db.execute(
            select(func.count()).select_from(
                select(Inventory.id).where(
                    Inventory.store_id == store_id,
                    Inventory.qty_on_hand <= 0,
                ).subquery()
            )
        )
        out_of_stock = inv_result.scalar() or 0
        if out_of_stock > 0:
            insights.append(AIInsight(
                category="inventory",
                severity="critical",
                title=f"{out_of_stock} SKUs out of stock",
                detail="These items cannot be sold until restocked",
                action="Place emergency reorder immediately",
            ))

    return insights


# ──────────────────── Gemini Summary ─────────────────────


async def generate_gemini_summary(
    report_data: dict,
    store_id: Optional[UUID] = None,
) -> Optional[str]:
    """Send the analytics data to Gemini for a natural-language executive summary.

    Routes through ai_gateway for timeout / fallback / logging / cost tracking.
    Returns None if Gemini is unavailable.
    """
    from app.services.ai_gateway import AIRequest, SYNC_TIMEOUT_SECONDS, invoke

    prompt = f"""You are a retail analytics advisor for a Singapore jewelry store.
Analyze this data and provide a concise executive summary (3-5 paragraphs) with
actionable recommendations. Focus on profitability, inventory health, and growth
opportunities. Reference specific SKUs and numbers.

DATA:
{json.dumps(report_data, indent=2, default=str)[:8000]}

Respond in professional business English. No markdown formatting."""

    resp = await invoke(
        AIRequest(
            prompt=prompt,
            purpose="analytics_summary",
            timeout_seconds=SYNC_TIMEOUT_SECONDS,
            max_output_tokens=1024,
            store_id=store_id,
        ),
        fallback_text="",
    )

    if resp.is_fallback or not resp.text.strip():
        return None
    return resp.text.strip()
