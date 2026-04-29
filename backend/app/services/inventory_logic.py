"""Inventory business logic — stock deduction, reorder intelligence."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from app.firestore_helpers import get_document, query_collection, update_document
from app.schemas.inventory import InventoryType
from app.schemas.supply_chain import SupplyActionSource
from app.services.supply_chain import adjust_stage_inventory, ensure_finished_stage_inventory, list_stage_inventory

logger = logging.getLogger(__name__)


def _stock_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/stock"


def _sku_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/inventory"


async def deduct_stock_for_order(
    store_id: UUID,
    items: list[dict],
    actor_user_id: UUID | None = None,
) -> list[str]:
    """Deduct inventory for each order line item.

    Args:
        items: list of dicts with keys ``sku_id`` and ``qty``.

    Returns:
        list of warning messages (e.g. stock went below reorder level).
    """
    warnings: list[str] = []
    system_actor_id = actor_user_id or UUID(int=0)
    stock_rows = {
        str(row.get("sku_id")): row
        for row in query_collection(_stock_collection(store_id))
        if row.get("sku_id")
    }

    for item in items:
        sku_id = item["sku_id"]
        qty = item["qty"]
        stage = ensure_finished_stage_inventory(
            store_id,
            UUID(str(sku_id)),
            system_actor_id,
            source=SupplyActionSource.system,
        )
        if stage is None:
            logger.warning("No inventory record for SKU %s in store %s", sku_id, store_id)
            continue
        new_qty = stage.quantity_on_hand - qty
        reorder_level = int(stock_rows.get(str(sku_id), {}).get("reorder_level", 0) or 0)
        adjust_stage_inventory(
            store_id,
            UUID(str(sku_id)),
            InventoryType.finished,
            system_actor_id,
            delta_qty=-qty,
            source=SupplyActionSource.system,
            reference_type="order",
        )

        if new_qty < 0:
            warnings.append(f"SKU {sku_id}: stock went negative ({new_qty})")
        elif new_qty <= reorder_level:
            warnings.append(f"SKU {sku_id}: stock ({new_qty}) at or below reorder level ({reorder_level})")

    return warnings


async def reorder_recommendations(
    store_id: UUID,
    lookback_days: int = 30,
) -> list[dict]:
    """Generate intelligent reorder recommendations based on sales velocity."""
    LEAD_DAYS = 7
    SAFETY_BUFFER_DAYS = 3

    sku_collection = _sku_collection(store_id)
    sku_rows = {
        str(row.get("id")): row
        for row in query_collection(sku_collection)
        if row.get("id")
    }
    stock_rows = {
        str(row.get("sku_id")): row
        for row in query_collection(_stock_collection(store_id))
        if row.get("sku_id")
    }
    finished_positions = {
        str(position.sku_id): position
        for position in list_stage_inventory(store_id, inventory_type=InventoryType.finished)
    }
    low_items = []
    for sku_id, stock_row in stock_rows.items():
        finished_qty = finished_positions.get(sku_id).quantity_on_hand if sku_id in finished_positions else 0
        reorder_level = int(stock_row.get("reorder_level", 0) or 0)
        if finished_qty <= reorder_level:
            low_items.append(
                {
                    "sku_id": sku_id,
                    "qty_on_hand": finished_qty,
                    "reorder_level": reorder_level,
                    "reorder_qty": int(stock_row.get("reorder_qty", 1) or 1),
                }
            )

    if not low_items:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    # Get orders for the lookback period
    orders = query_collection(
        f"stores/{store_id}/orders",
        filters=[("order_date", ">=", cutoff.date().isoformat())],
    )
    orders = [o for o in orders if o.get("status") != "voided"]

    # Aggregate total qty sold per SKU
    sku_sold: dict[str, int] = {}
    for order in orders:
        for item in order.get("items", []):
            sid = item.get("sku_id", "")
            sku_sold[sid] = sku_sold.get(sid, 0) + int(item.get("qty", 0))

    recommendations = []
    for inv in low_items:
        sku_id = inv.get("sku_id", "")
        qty_on_hand = int(inv.get("qty_on_hand", 0))
        reorder_level = int(inv.get("reorder_level", 0))
        reorder_qty = int(inv.get("reorder_qty", 1))

        total_sold = sku_sold.get(sku_id, 0)
        avg_daily = total_sold / lookback_days if lookback_days > 0 else 0

        days_until_stockout = qty_on_hand / avg_daily if avg_daily > 0 else float("inf")

        if avg_daily > 0:
            recommended_qty = int(
                Decimal(str((LEAD_DAYS + SAFETY_BUFFER_DAYS) * avg_daily))
                .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )
            recommended_qty = max(recommended_qty, reorder_qty)
        else:
            recommended_qty = reorder_qty

        sku = sku_rows.get(str(sku_id)) or get_document(sku_collection, str(sku_id))

        recommendations.append({
            "sku_id": str(sku_id),
            "sku_code": sku.get("sku_code", "UNKNOWN") if sku else "UNKNOWN",
            "description": sku.get("description", "") if sku else "",
            "qty_on_hand": qty_on_hand,
            "reorder_level": reorder_level,
            "avg_daily_sales": round(avg_daily, 2),
            "days_until_stockout": round(days_until_stockout, 1) if days_until_stockout != float("inf") else None,
            "recommended_order_qty": recommended_qty,
            "urgency": "critical" if days_until_stockout <= 3 else "high" if days_until_stockout <= 7 else "medium",
        })

    urgency_order = {"critical": 0, "high": 1, "medium": 2}
    recommendations.sort(key=lambda r: urgency_order.get(r["urgency"], 99))

    return recommendations
