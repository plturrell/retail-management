"""Gemini-powered pricing strategist — synchronous product feature.

Routes through ai_gateway for timeout / fallback / logging / cost tracking.
Bounded response: single JSON object ≤ 512 tokens.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from app.services.ai_gateway import AIRequest, SYNC_TIMEOUT_SECONDS, invoke

logger = logging.getLogger(__name__)


class PricingStrategyUpdate(BaseModel):
    store_name: str
    recommended_discount_rate: float
    recommended_margin: float
    reasoning: str
    action: str  # "APPROVE", "HOLD", "ALERT"
    request_id: Optional[str] = None
    is_fallback: bool = False
    latency_ms: Optional[int] = None
    cost_usd: Optional[float] = None


class PricingCritique(BaseModel):
    store_type: str
    suggested_price_sgd: float
    status: str  # "TOO_LOW", "OPTIMAL", "TOO_HIGH"
    critique: str
    request_id: Optional[str] = None
    is_fallback: bool = False
    latency_ms: Optional[int] = None
    cost_usd: Optional[float] = None


def _parse_json_response(text: str) -> dict:
    """Safely extract JSON from Gemini's response, handling markdown fences."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        text = match.group(1).strip()
    return json.loads(text)


async def get_dynamic_pricing_strategy(
    store_name: str,
    current_discount: float,
    cogs_sgd: float,
    target_margin: float,
    recent_sales_velocity: str = "moderate",
    sales_context: Optional[dict] = None,
    store_id: Optional[UUID] = None,
) -> PricingStrategyUpdate:
    """Invoke Gemini via ai_gateway to evaluate pricing parameters."""

    context_block = ""
    if sales_context:
        context_block = f"""
REAL SALES DATA (last 30 days):
- Total Revenue: ${sales_context.get('total_revenue', 0):,.2f} SGD
- Order Count: {sales_context.get('order_count', 0)}
- Avg Order Value: ${sales_context.get('avg_order_value', 0):,.2f} SGD
- Top Sellers: {json.dumps(sales_context.get('top_sellers', [])[:5])}
- Low Margin SKUs: {json.dumps(sales_context.get('low_margin_skus', [])[:5])}
- Inventory Alerts: {sales_context.get('inventory_alerts', 0)} items below reorder
"""

    prompt = f"""You are a retail pricing strategist for a Singapore jewelry store.
Store: {store_name}

CURRENT PARAMETERS:
- Base Production Cost: ${cogs_sgd:.2f} SGD
- Current Discount Rate: {current_discount * 100:.1f}%
- Target Margin: {target_margin * 100:.1f}%
- Sales Velocity: {recent_sales_velocity}
- Singapore GST: 9%
{context_block}
Should the discount rate or target margin be adjusted to optimize gross profit?

Respond ONLY with a JSON object:
{{
    "store_name": "{store_name}",
    "recommended_discount_rate": <float 0-1>,
    "recommended_margin": <float 0-1>,
    "reasoning": "<2-3 sentences>",
    "action": "APPROVE" | "HOLD" | "ALERT"
}}"""

    fallback = json.dumps({
        "store_name": store_name,
        "recommended_discount_rate": current_discount,
        "recommended_margin": target_margin,
        "reasoning": "AI unavailable — returning current parameters",
        "action": "HOLD",
    })

    resp = await invoke(
        AIRequest(
            prompt=prompt,
            purpose="pricing_strategy",
            timeout_seconds=SYNC_TIMEOUT_SECONDS,
            max_output_tokens=512,
            store_id=store_id,
        ),
        fallback_text=fallback,
    )

    try:
        result = _parse_json_response(resp.text)
        return PricingStrategyUpdate(
            **result,
            request_id=resp.request_id,
            is_fallback=resp.is_fallback,
            latency_ms=resp.latency_ms,
            cost_usd=resp.estimated_cost_usd,
        )
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Failed to parse pricing response: %s", exc)
        return PricingStrategyUpdate(
            store_name=store_name,
            recommended_discount_rate=current_discount,
            recommended_margin=target_margin,
            reasoning=f"Parse error — returning current parameters: {exc}",
            action="HOLD",
            request_id=resp.request_id,
            is_fallback=True,
            latency_ms=resp.latency_ms,
        )


async def audit_retail_pricing(
    store_name: str,
    store_type: str,  # "GTO" or "FIXED"
    bom_cost_cny: float,
    current_retail_price: float,
    store_id: Optional[UUID] = None,
) -> PricingCritique:
    """Invoke Gemini to rigorously audit and challenge retail pricing based on operational math."""
    
    # Pre-calculated mathematical parameters ensuring Gemini stays accurate
    cogs_sgd = bom_cost_cny / 5.34
    
    if store_type == "GTO":
        math_context = f"""
CONCESSION MATH (GTO):
- Cost of Goods: ${cogs_sgd:.2f} SGD
- Base Wage Overhead: $2.66 SGD
- Target Margin required: 35%
- GTO (Takashimaya/Isetan Tax): 32%
- Payment Gateway Commission: 5%
- GST Factor: 9%
Warning: High erosion risk. To survive concession, the price must cover 32% gross turnover BEFORE the 35% margin is realized.
"""
    else:
        math_context = f"""
OWN BRAND MATH (FIXED):
- Cost of Goods: ${cogs_sgd:.2f} SGD
- Base Wage Overhead: $2.66 SGD
- Fixed Rent Overhead per unit: $13.33 SGD
- Target Margin required: 35%
- Payment Gateway Commission: 5%
- GST Factor: 9%
Note: Own Brand relies on volume to cover the fixed $13.33 layout. The price must be high enough to hit 35% margin after rent extraction.
"""

    prompt = f"""You are a strict, elite Financial Retail Auditor for a Singapore jewelry company.
Your job is to challenge the proposed retail price for an item at {store_name} ({store_type}).

CURRENT FINANCIALS:
- Manufacturing BOM Cost: {bom_cost_cny:.2f} CNY
- Currently Proposed Retail Price: ${current_retail_price:.2f} SGD

{math_context}

Evaluate if the currently proposed retail price of ${current_retail_price:.2f} SGD is dangerous.
Calculate the mathematically perfect retail price to hit the exact 35% margin constraint.
If the current price is TOO_LOW, give a harsh critique explaining why it fails the margin requirements (e.g. failing to account for the GTO extraction).
If the current price is TOO_HIGH, critique that it will cause slow inventory velocity without tangible margin upside.

Respond ONLY with a JSON object:
{{
    "store_type": "{store_type}",
    "suggested_price_sgd": <float>,
    "status": "TOO_LOW" | "OPTIMAL" | "TOO_HIGH",
    "critique": "<2-3 sentences of blunt financial explanation>"
}}"""

    fallback = json.dumps({
        "store_type": store_type,
        "suggested_price_sgd": current_retail_price,
        "status": "OPTIMAL",
        "critique": "AI unavailable — auto-passing price as optimal."
    })

    resp = await invoke(
        AIRequest(
            prompt=prompt,
            purpose="pricing_audit",
            timeout_seconds=SYNC_TIMEOUT_SECONDS,
            max_output_tokens=512,
            store_id=store_id,
        ),
        fallback_text=fallback,
    )

    try:
        result = _parse_json_response(resp.text)
        return PricingCritique(
            **result,
            request_id=resp.request_id,
            is_fallback=resp.is_fallback,
            latency_ms=resp.latency_ms,
            cost_usd=resp.estimated_cost_usd,
        )
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Failed to parse audit response: %s", exc)
        return PricingCritique(
            store_type=store_type,
            suggested_price_sgd=current_retail_price,
            status="OPTIMAL",
            critique=f"Parse error — {exc}",
            request_id=resp.request_id,
            is_fallback=True,
            latency_ms=resp.latency_ms,
        )
