"""Pricing strategy endpoints powered by Gemini AI with real sales data."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.inventory import Inventory, SKU
from app.models.order import Order, OrderItem, OrderStatus
from app.models.user import UserStoreRole
from app.auth.dependencies import require_store_access
from app.services.gemini_strategist import (
    PricingCritique,
    PricingStrategyUpdate,
    audit_retail_pricing,
    get_dynamic_pricing_strategy,
)

router = APIRouter(prefix="/api/stores/{store_id}/strategy", tags=["pricing-strategy"])


class PricingContext(BaseModel):
    current_discount: float
    cogs_sgd: float
    target_margin: float
    sales_velocity: str = "moderate"


@router.post("/dynamic_pricing", response_model=PricingStrategyUpdate)
async def evaluate_dynamic_pricing(
    store_id: UUID,
    context: PricingContext,
    _: UserStoreRole = Depends(require_store_access),
    db: AsyncSession = Depends(get_db),
):
    """Evaluate pricing strategy using Gemini with real sales data from the DB."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)

    # Gather real sales context from the database
    orders_q = select(Order).where(
        Order.store_id == store_id,
        Order.status != OrderStatus.voided,
        Order.order_date >= cutoff,
    )
    result = await db.execute(orders_q)
    orders = result.scalars().all()

    total_revenue = sum(float(o.grand_total) for o in orders)
    order_count = len(orders)
    avg_order_value = total_revenue / order_count if order_count > 0 else 0.0

    # Top sellers
    top_q = (
        select(
            SKU.sku_code,
            SKU.description,
            func.sum(OrderItem.qty).label("qty"),
        )
        .select_from(OrderItem)
        .join(Order, OrderItem.order_id == Order.id)
        .join(SKU, OrderItem.sku_id == SKU.id)
        .where(
            Order.store_id == store_id,
            Order.status != OrderStatus.voided,
            Order.order_date >= cutoff,
        )
        .group_by(SKU.sku_code, SKU.description)
        .order_by(func.sum(OrderItem.qty).desc())
        .limit(5)
    )
    top_result = await db.execute(top_q)
    top_sellers = [
        {"sku": row[0], "desc": row[1], "qty": int(row[2])}
        for row in top_result.all()
    ]

    # Low margin SKUs (cost_price > 70% of selling price)
    low_margin_q = (
        select(SKU.sku_code, SKU.description, SKU.cost_price)
        .where(SKU.store_id == store_id, SKU.cost_price.isnot(None))
        .limit(5)
    )
    lm_result = await db.execute(low_margin_q)
    low_margin_skus = [
        {"sku": row[0], "cost": float(row[2])} for row in lm_result.all()
    ]

    # Inventory alerts count
    alert_q = select(func.count()).select_from(
        select(Inventory.id).where(
            Inventory.store_id == store_id,
            Inventory.qty_on_hand <= Inventory.reorder_level,
        ).subquery()
    )
    alert_result = await db.execute(alert_q)
    inventory_alerts = alert_result.scalar() or 0

    # Fetch store name
    from app.models.store import Store
    store_result = await db.execute(select(Store.name).where(Store.id == store_id))
    store_name = store_result.scalar_one_or_none() or str(store_id)

    sales_context = {
        "total_revenue": total_revenue,
        "order_count": order_count,
        "avg_order_value": avg_order_value,
        "top_sellers": top_sellers,
        "low_margin_skus": low_margin_skus,
        "inventory_alerts": inventory_alerts,
    }

    strategy = await get_dynamic_pricing_strategy(
        store_name=store_name,
        current_discount=context.current_discount,
        cogs_sgd=context.cogs_sgd,
        target_margin=context.target_margin,
        recent_sales_velocity=context.sales_velocity,
        sales_context=sales_context,
        store_id=store_id,
    )

    return strategy


class PricingAuditRequest(BaseModel):
    store_name: str
    store_type: str  # "GTO" or "FIXED"
    bom_cost_cny: float
    current_retail_price: float


@router.post("/audit_pricing", response_model=PricingCritique)
async def execute_pricing_audit(
    store_id: UUID,
    request: PricingAuditRequest,
    _: UserStoreRole = Depends(require_store_access),
):
    """Rigorous algorithmic Gemini pricing critique comparing actuals to ideal mathematical targets."""
    
    critique = await audit_retail_pricing(
        store_name=request.store_name,
        store_type=request.store_type,
        bom_cost_cny=request.bom_cost_cny,
        current_retail_price=request.current_retail_price,
        store_id=store_id,
    )
    
    return critique
