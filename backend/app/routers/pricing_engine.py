"""Pricing strategy endpoints powered by Gemini AI with real sales data."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from google.cloud.firestore_v1.client import Client as FirestoreClient

from app.firestore import get_firestore_db
from app.firestore_helpers import get_document, query_collection
from app.auth.dependencies import require_store_access
from app.schemas.inventory import InventoryType
from app.services.gemini_strategist import (
    PricingCritique,
    PricingStrategyUpdate,
    audit_retail_pricing,
    get_dynamic_pricing_strategy,
)
from app.services.supply_chain import list_stage_inventory

router = APIRouter(prefix="/api/stores/{store_id}/strategy", tags=["pricing-strategy"])


def _sku_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/inventory"


def _stock_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/stock"


class PricingContext(BaseModel):
    current_discount: float
    cogs_sgd: float
    target_margin: float
    sales_velocity: str = "moderate"


@router.post("/dynamic_pricing", response_model=PricingStrategyUpdate)
async def evaluate_dynamic_pricing(
    store_id: UUID,
    context: PricingContext,
    _: dict = Depends(require_store_access),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Evaluate pricing strategy using Gemini with real sales data."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)

    orders = query_collection(
        f"stores/{store_id}/orders",
        filters=[("order_date", ">=", cutoff.date().isoformat())],
    )
    orders = [o for o in orders if o.get("status") != "voided"]

    total_revenue = sum(float(o.get("grand_total", 0)) for o in orders)
    order_count = len(orders)
    avg_order_value = total_revenue / order_count if order_count > 0 else 0.0

    # Top sellers — aggregate from embedded items
    sku_qty: dict[str, int] = {}
    for o in orders:
        for item in o.get("items", []):
            sid = item.get("sku_id", "")
            sku_qty[sid] = sku_qty.get(sid, 0) + int(item.get("qty", 0))
    sorted_skus = sorted(sku_qty.items(), key=lambda x: x[1], reverse=True)[:5]
    top_sellers = []
    for sid, qty in sorted_skus:
        sku = get_document(_sku_collection(store_id), sid)
        top_sellers.append({
            "sku": sku.get("sku_code", "UNKNOWN") if sku else "UNKNOWN",
            "desc": sku.get("description", "") if sku else "",
            "qty": qty,
        })

    # Low margin SKUs
    all_skus = query_collection(_sku_collection(store_id), limit=5)
    low_margin_skus = [
        {"sku": s.get("sku_code", ""), "cost": float(s.get("cost_price", 0))}
        for s in all_skus if s.get("cost_price")
    ]

    # Inventory alerts
    finished_positions = {
        str(position.sku_id): position
        for position in list_stage_inventory(store_id, inventory_type=InventoryType.finished)
    }
    inventory_alerts = len(
        [
            row
            for row in query_collection(_stock_collection(store_id))
            if finished_positions.get(str(row.get("sku_id")))
            and finished_positions[str(row.get("sku_id"))].quantity_on_hand
            <= int(row.get("reorder_level", 0) or 0)
        ]
    )

    # Store name
    store_doc = get_document("stores", str(store_id))
    store_name = store_doc.get("name", str(store_id)) if store_doc else str(store_id)

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
    _: dict = Depends(require_store_access),
):
    """Rigorous algorithmic Gemini pricing critique."""
    critique = await audit_retail_pricing(
        store_name=request.store_name,
        store_type=request.store_type,
        bom_cost_cny=request.bom_cost_cny,
        current_retail_price=request.current_retail_price,
        store_id=store_id,
    )
    return critique
