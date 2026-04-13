"""Evaluation dataset for analytics insights and margin calculations.

Tests the rule-based insight engine against known scenarios to ensure
correct severity classification, trend detection, and margin health labels.
"""
from __future__ import annotations

import pytest

from app.services.ai_analytics import (
    AIInsight,
    DemandForecast,
    MarginItem,
    SalesTrend,
    generate_insights,
)


# ── Synthetic data ───────────────────────────────────────────────

HEALTHY_MARGINS = [
    MarginItem(
        sku_id="a1", sku_code="VE-JWL-001", description="Gold Ring",
        cost_price=100.0, selling_price=250.0, margin_pct=60.0,
        total_sold=50, total_revenue=12500.0, total_profit=7500.0,
        health="healthy",
    ),
    MarginItem(
        sku_id="a2", sku_code="VE-JWL-002", description="Silver Pendant",
        cost_price=30.0, selling_price=80.0, margin_pct=62.5,
        total_sold=100, total_revenue=8000.0, total_profit=5000.0,
        health="healthy",
    ),
]

THIN_MARGINS = [
    MarginItem(
        sku_id="b1", sku_code="VE-JWL-010", description="Costume Ring",
        cost_price=45.0, selling_price=50.0, margin_pct=5.0,
        total_sold=200, total_revenue=10000.0, total_profit=1000.0,
        health="thin",
    ),
    MarginItem(
        sku_id="b2", sku_code="VE-JWL-011", description="Clearance Bracelet",
        cost_price=60.0, selling_price=55.0, margin_pct=-9.1,
        total_sold=50, total_revenue=2750.0, total_profit=-250.0,
        health="negative",
    ),
]

GROWING_TRENDS = [
    SalesTrend(period="2026-03-03", total_sales=5000.0, order_count=20, avg_order_value=250.0),
    SalesTrend(period="2026-03-10", total_sales=8000.0, order_count=32, avg_order_value=250.0),
]

DECLINING_TRENDS = [
    SalesTrend(period="2026-03-03", total_sales=10000.0, order_count=40, avg_order_value=250.0),
    SalesTrend(period="2026-03-10", total_sales=6000.0, order_count=24, avg_order_value=250.0),
]

RISING_FORECASTS = [
    DemandForecast(
        sku_id="c1", sku_code="VE-JWL-020", description="Opal Earring",
        avg_daily_sales=5.0, trend="rising", forecast_next_7d=42.0, forecast_next_30d=180.0,
    ),
]

DECLINING_FORECASTS = [
    DemandForecast(
        sku_id="c2", sku_code="VE-JWL-021", description="Jade Bangle",
        avg_daily_sales=1.0, trend="declining", forecast_next_7d=5.0, forecast_next_30d=20.0,
    ),
]


# ── Tests ────────────────────────────────────────────────────────

class TestInsightGeneration:

    @pytest.mark.asyncio
    async def test_healthy_margins_no_margin_alert(self) -> None:
        insights = await generate_insights(None, None, HEALTHY_MARGINS, GROWING_TRENDS, [])
        margin_insights = [i for i in insights if i.category == "margin"]
        assert len(margin_insights) == 0, "Healthy margins should not trigger alerts"

    @pytest.mark.asyncio
    async def test_thin_margins_trigger_alert(self) -> None:
        insights = await generate_insights(None, None, THIN_MARGINS, [], [])
        margin_insights = [i for i in insights if i.category == "margin"]
        assert len(margin_insights) == 1
        assert margin_insights[0].severity == "critical"  # has a negative margin item

    @pytest.mark.asyncio
    async def test_growing_revenue_is_info(self) -> None:
        insights = await generate_insights(None, None, [], GROWING_TRENDS, [])
        rev_insights = [i for i in insights if i.category == "revenue"]
        assert len(rev_insights) == 1
        assert rev_insights[0].severity == "info"
        assert "grew" in rev_insights[0].title.lower()

    @pytest.mark.asyncio
    async def test_declining_revenue_is_warning(self) -> None:
        insights = await generate_insights(None, None, [], DECLINING_TRENDS, [])
        rev_insights = [i for i in insights if i.category == "revenue"]
        assert len(rev_insights) == 1
        assert rev_insights[0].severity == "warning"
        assert "declined" in rev_insights[0].title.lower()

    @pytest.mark.asyncio
    async def test_rising_demand_detected(self) -> None:
        insights = await generate_insights(None, None, [], [], RISING_FORECASTS)
        trend_insights = [i for i in insights if i.category == "trend"]
        assert any("rising" in i.title.lower() for i in trend_insights)

    @pytest.mark.asyncio
    async def test_declining_demand_detected(self) -> None:
        insights = await generate_insights(None, None, [], [], DECLINING_FORECASTS)
        trend_insights = [i for i in insights if i.category == "trend"]
        assert any("declining" in i.title.lower() for i in trend_insights)


class TestMarginHealth:
    """Validate margin health classification."""

    def test_healthy_above_30(self) -> None:
        assert HEALTHY_MARGINS[0].health == "healthy"
        assert HEALTHY_MARGINS[0].margin_pct >= 30

    def test_thin_below_10(self) -> None:
        assert THIN_MARGINS[0].health == "thin"
        assert THIN_MARGINS[0].margin_pct < 10

    def test_negative_margin(self) -> None:
        assert THIN_MARGINS[1].health == "negative"
        assert THIN_MARGINS[1].margin_pct < 0
