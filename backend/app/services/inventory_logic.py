"""Inventory business logic — stock deduction, reorder intelligence."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import Inventory, SKU
from app.models.order import Order, OrderItem, OrderStatus

logger = logging.getLogger(__name__)


async def deduct_stock_for_order(
    db: AsyncSession,
    store_id: UUID,
    items: list[dict],
) -> list[str]:
    """Deduct inventory for each order line item.

    Args:
        items: list of dicts with keys ``sku_id`` and ``qty``.

    Returns:
        list of warning messages (e.g. stock went below reorder level).
    """
    warnings: list[str] = []

    for item in items:
        sku_id = item["sku_id"]
        qty = item["qty"]

        result = await db.execute(
            select(Inventory).where(
                Inventory.sku_id == sku_id,
                Inventory.store_id == store_id,
            ).with_for_update()
        )
        inv = result.scalar_one_or_none()
        if inv is None:
            logger.warning("No inventory record for SKU %s in store %s", sku_id, store_id)
            continue

        inv.qty_on_hand -= qty
        inv.last_updated = datetime.now(timezone.utc)

        if inv.qty_on_hand < 0:
            warnings.append(
                f"SKU {sku_id}: stock went negative ({inv.qty_on_hand})"
            )
        elif inv.qty_on_hand <= inv.reorder_level:
            warnings.append(
                f"SKU {sku_id}: stock ({inv.qty_on_hand}) at or below reorder level ({inv.reorder_level})"
            )

    return warnings


async def reorder_recommendations(
    db: AsyncSession,
    store_id: UUID,
    lookback_days: int = 30,
) -> list[dict]:
    """Generate intelligent reorder recommendations based on sales velocity.

    For each SKU below reorder level:
      - Calculates avg daily sales over the lookback period
      - Estimates days until stockout
      - Recommends order quantity = (lead_days + safety_buffer) * daily_rate

    Returns list of recommendation dicts.
    """
    LEAD_DAYS = 7  # assumed supplier lead time
    SAFETY_BUFFER_DAYS = 3

    # Find low-stock items
    low_stock_q = select(Inventory).where(
        Inventory.store_id == store_id,
        Inventory.qty_on_hand <= Inventory.reorder_level,
    )
    result = await db.execute(low_stock_q)
    low_items = result.scalars().all()

    if not low_items:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    recommendations = []
    for inv in low_items:
        # Calculate avg daily sales for this SKU
        sales_q = (
            select(func.coalesce(func.sum(OrderItem.qty), 0))
            .select_from(OrderItem)
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                Order.store_id == store_id,
                Order.status != OrderStatus.voided,
                Order.order_date >= cutoff,
                OrderItem.sku_id == inv.sku_id,
            )
        )
        sales_result = await db.execute(sales_q)
        total_sold = int(sales_result.scalar() or 0)
        avg_daily = total_sold / lookback_days if lookback_days > 0 else 0

        # Estimate days until stockout
        days_until_stockout = (
            inv.qty_on_hand / avg_daily if avg_daily > 0 else float("inf")
        )

        # Recommended order qty
        if avg_daily > 0:
            recommended_qty = int(
                Decimal(str((LEAD_DAYS + SAFETY_BUFFER_DAYS) * avg_daily))
                .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )
            recommended_qty = max(recommended_qty, inv.reorder_qty)
        else:
            recommended_qty = inv.reorder_qty

        # Fetch SKU details
        sku_result = await db.execute(select(SKU).where(SKU.id == inv.sku_id))
        sku = sku_result.scalar_one_or_none()

        recommendations.append({
            "sku_id": str(inv.sku_id),
            "sku_code": sku.sku_code if sku else "UNKNOWN",
            "description": sku.description if sku else "",
            "qty_on_hand": inv.qty_on_hand,
            "reorder_level": inv.reorder_level,
            "avg_daily_sales": round(avg_daily, 2),
            "days_until_stockout": round(days_until_stockout, 1) if days_until_stockout != float("inf") else None,
            "recommended_order_qty": recommended_qty,
            "urgency": "critical" if days_until_stockout <= 3 else "high" if days_until_stockout <= 7 else "medium",
        })

    # Sort by urgency
    urgency_order = {"critical": 0, "high": 1, "medium": 2}
    recommendations.sort(key=lambda r: urgency_order.get(r["urgency"], 99))

    return recommendations
