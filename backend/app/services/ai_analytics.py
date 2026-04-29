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

from app.schemas.inventory import InventoryType
from app.firestore_helpers import get_document, query_collection
from app.services.supply_chain import list_stage_inventory

logger = logging.getLogger(__name__)


def _sku_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/inventory"


def _price_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/prices"


def _stock_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/stock"


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
    store_id: UUID,
    from_date: date,
    to_date: date,
) -> list[MarginItem]:
    """Calculate profit margins per SKU from actual sales data."""
    # Get orders for the period (non-voided)
    orders = query_collection(
        f"stores/{store_id}/orders",
        filters=[
            ("order_date", ">=", from_date.isoformat()),
            ("order_date", "<=", to_date.isoformat()),
        ],
    )

    # Aggregate sales by SKU from embedded order items
    sku_agg: dict[str, dict] = {}
    for order in orders:
        if order.get("status") == "voided":
            continue
        for item in order.get("items", []):
            sid = item.get("sku_id", "")
            if sid not in sku_agg:
                sku_agg[sid] = {"total_qty": 0, "total_revenue": 0.0}
            sku_agg[sid]["total_qty"] += int(item.get("qty", 0))
            sku_agg[sid]["total_revenue"] += float(item.get("line_total", 0))

    items: list[MarginItem] = []
    for sku_id, agg in sku_agg.items():
        sku = get_document(_sku_collection(store_id), sku_id)
        if sku is None:
            continue

        cost = float(sku.get("cost_price", 0)) if sku.get("cost_price") else None
        revenue = agg["total_revenue"]
        qty = agg["total_qty"]

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
        prices = query_collection(
            _price_collection(store_id),
            filters=[("sku_id", "==", sku_id)],
            order_by="-valid_from",
            limit=1,
        )
        selling_price = float(prices[0].get("price_incl_tax", 0)) if prices else None

        items.append(MarginItem(
            sku_id=str(sku_id),
            sku_code=sku.get("sku_code", "UNKNOWN"),
            description=sku.get("description", ""),
            cost_price=cost,
            selling_price=selling_price,
            margin_pct=margin_pct,
            total_sold=qty,
            total_revenue=round(revenue, 2),
            total_profit=round(profit, 2),
            health=health,
        ))

    items.sort(key=lambda x: x.total_profit, reverse=True)
    return items


# ──────────────────── Sales Trends ───────────────────────


async def compute_sales_trends(
    store_id: UUID,
    from_date: date,
    to_date: date,
    granularity: str = "weekly",
) -> list[SalesTrend]:
    """Aggregate sales into weekly or daily buckets for trend analysis."""
    orders = query_collection(
        f"stores/{store_id}/orders",
        filters=[
            ("order_date", ">=", from_date.isoformat()),
            ("order_date", "<=", to_date.isoformat()),
        ],
        order_by="order_date",
    )

    # Filter out voided
    orders = [o for o in orders if o.get("status") != "voided"]

    def _get_date(o):
        od = o.get("order_date", "")
        if isinstance(od, str):
            return date.fromisoformat(od[:10])
        return od.date() if hasattr(od, "date") else od

    if granularity == "daily":
        bucket_fn = lambda o: _get_date(o).isoformat()
    else:
        bucket_fn = lambda o: (_get_date(o) - timedelta(days=_get_date(o).weekday())).isoformat()

    buckets: dict[str, list] = {}
    for o in orders:
        key = bucket_fn(o)
        buckets.setdefault(key, []).append(o)

    trends = []
    for period, period_orders in sorted(buckets.items()):
        total = sum(float(o.get("grand_total", 0)) for o in period_orders)
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
    store_id: UUID,
    lookback_days: int = 60,
    top_n: int = 20,
) -> list[DemandForecast]:
    """Simple linear trend-based demand forecast per SKU."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)
    midpoint = now - timedelta(days=lookback_days // 2)

    # Get all orders in lookback window
    orders = query_collection(
        f"stores/{store_id}/orders",
        filters=[("order_date", ">=", cutoff.date().isoformat())],
    )
    orders = [o for o in orders if o.get("status") != "voided"]

    # Aggregate by SKU
    sku_totals: dict[str, int] = {}
    sku_older: dict[str, int] = {}
    sku_newer: dict[str, int] = {}
    for order in orders:
        od = order.get("order_date", "")
        if isinstance(od, str):
            order_date = datetime.fromisoformat(od)
        else:
            order_date = od
        for item in order.get("items", []):
            sid = item.get("sku_id", "")
            qty = int(item.get("qty", 0))
            sku_totals[sid] = sku_totals.get(sid, 0) + qty
            if order_date < midpoint:
                sku_older[sid] = sku_older.get(sid, 0) + qty
            else:
                sku_newer[sid] = sku_newer.get(sid, 0) + qty

    # Sort by total qty, take top_n
    sorted_skus = sorted(sku_totals.items(), key=lambda x: x[1], reverse=True)[:top_n]

    forecasts = []
    for sku_id, total_qty in sorted_skus:
        avg_daily = total_qty / lookback_days

        older_sales = sku_older.get(sku_id, 0)
        newer_sales = sku_newer.get(sku_id, 0)

        if older_sales > 0:
            change_pct = (newer_sales - older_sales) / older_sales
            trend = "rising" if change_pct > 0.15 else "declining" if change_pct < -0.15 else "stable"
            trend_multiplier = 1 + (change_pct * 0.5)
        else:
            trend = "stable"
            trend_multiplier = 1.0

        forecast_daily = avg_daily * trend_multiplier
        forecast_7d = round(forecast_daily * 7, 1)
        forecast_30d = round(forecast_daily * 30, 1)

        sku = get_document(_sku_collection(store_id), sku_id)

        forecasts.append(DemandForecast(
            sku_id=str(sku_id),
            sku_code=sku.get("sku_code", "UNKNOWN") if sku else "UNKNOWN",
            description=sku.get("description", "") if sku else "",
            avg_daily_sales=round(avg_daily, 2),
            trend=trend,
            forecast_next_7d=forecast_7d,
            forecast_next_30d=forecast_30d,
        ))

    return forecasts


# ──────────────────── Rule-Based Insights ────────────────


async def generate_insights(
    store_id: UUID | None,
    margins: list[MarginItem] | None = None,
    trends: list[SalesTrend] | None = None,
    forecasts: list[DemandForecast] | None = None,
    legacy_forecasts: list[DemandForecast] | None = None,
) -> list[AIInsight]:
    """Generate actionable insights from computed analytics."""
    if legacy_forecasts is not None:
        margins, trends, forecasts = trends, forecasts, legacy_forecasts
    margins = margins or []
    trends = trends or []
    forecasts = forecasts or []
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

    # Inventory alerts from Firestore
    if store_id is not None:
        finished_positions = list_stage_inventory(
            store_id,
            inventory_type=InventoryType.finished,
        )
        stock_rows = {
            str(row.get("sku_id")): row
            for row in query_collection(_stock_collection(store_id))
            if row.get("sku_id")
        }
        out_of_stock = sum(
            1
            for position in finished_positions
            if str(position.sku_id) in stock_rows and position.quantity_on_hand <= 0
        )
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
