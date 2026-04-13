"""Inventory Copilot — AI-assisted inventory intelligence for store managers.

Endpoints:
  GET  /api/stores/{store_id}/copilot/summary
  GET  /api/stores/{store_id}/copilot/inventory
  GET  /api/stores/{store_id}/copilot/recommendations
  GET  /api/stores/{store_id}/copilot/adjustments
  POST /api/stores/{store_id}/copilot/recommendations/analyze
  POST /api/stores/{store_id}/copilot/recommendations/{rec_id}/approve
  POST /api/stores/{store_id}/copilot/recommendations/{rec_id}/reject
  POST /api/stores/{store_id}/copilot/recommendations/{rec_id}/apply
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, and_, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User, UserStoreRole, RoleEnum
from app.models.inventory import Inventory, SKU, Price
from app.models.purchase import PurchaseOrder
from app.models.supplier import Supplier
from app.models.copilot import (
    InventoryAdjustmentLog,
    ManagerRecommendation,
    RecommendationType,
    RecommendationStatus,
    WorkOrder,
    StockTransfer,
)
from app.auth.dependencies import get_current_user
from app.auth.dependencies import require_store_role
from app.schemas.common import DataResponse

router = APIRouter(
    prefix="/api/stores/{store_id}/copilot",
    tags=["copilot"],
)


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _rec_to_dict(r: ManagerRecommendation) -> dict:
    return {
        "id": str(r.id),
        "storeId": str(r.store_id),
        "skuId": str(r.sku_id) if r.sku_id else None,
        "inventoryId": str(r.inventory_id) if r.inventory_id else None,
        "inventoryType": r.inventory_type,
        "sourcingStrategy": r.sourcing_strategy,
        "supplierName": r.supplier_name,
        "type": r.rec_type,
        "status": r.status,
        "title": r.title,
        "rationale": r.rationale,
        "confidence": r.confidence,
        "supportingMetrics": r.supporting_metrics or {},
        "source": r.source,
        "expectedImpact": r.expected_impact,
        "currentPrice": float(r.current_price) if r.current_price else None,
        "suggestedPrice": float(r.suggested_price) if r.suggested_price else None,
        "suggestedOrderQty": r.suggested_order_qty,
        "workflowAction": r.workflow_action,
        "analysisStatus": r.analysis_status,
        "generatedAt": r.generated_at.isoformat() if r.generated_at else None,
        "decidedAt": r.decided_at.isoformat() if r.decided_at else None,
        "appliedAt": r.applied_at.isoformat() if r.applied_at else None,
        "note": r.note,
    }


async def _get_store_or_404(store_id: UUID, db: AsyncSession):
    from app.models.store import Store
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    return store


# ------------------------------------------------------------------ #
# GET /summary                                                         #
# ------------------------------------------------------------------ #

@router.get("/summary", response_model=DataResponse[dict])
async def copilot_summary(
    store_id: UUID,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    await _get_store_or_404(store_id, db)

    # Count low-stock items
    low_stock_q = await db.execute(
        select(func.count()).select_from(Inventory).where(
            Inventory.store_id == store_id,
            Inventory.qty_on_hand <= Inventory.reorder_level,
            Inventory.reorder_level > 0,
        )
    )
    low_stock_count = low_stock_q.scalar() or 0

    # Count pending recommendations by type
    pending_recs = await db.execute(
        select(ManagerRecommendation.rec_type, func.count()).where(
            ManagerRecommendation.store_id == store_id,
            ManagerRecommendation.status == "pending",
        ).group_by(ManagerRecommendation.rec_type)
    )
    rec_counts: dict[str, int] = {row[0]: row[1] for row in pending_recs}

    # Count open POs
    open_pos = await db.execute(
        select(func.count()).select_from(PurchaseOrder).where(
            PurchaseOrder.store_id == store_id,
            PurchaseOrder.status.in_(["draft", "submitted", "confirmed", "partially_received"]),
        )
    )
    open_po_count = open_pos.scalar() or 0

    # Count active work orders
    active_wo = await db.execute(
        select(func.count()).select_from(WorkOrder).where(
            WorkOrder.store_id == store_id,
            WorkOrder.status.in_(["scheduled", "in_progress"]),
        )
    )
    active_wo_count = active_wo.scalar() or 0

    # Count in-transit transfers
    in_transit = await db.execute(
        select(func.count()).select_from(StockTransfer).where(
            StockTransfer.store_id == store_id,
            StockTransfer.status == "in_transit",
        )
    )
    in_transit_count = in_transit.scalar() or 0

    # Count inventory units by type
    units_q = await db.execute(
        select(Inventory.inventory_type, func.sum(Inventory.qty_on_hand)).where(
            Inventory.store_id == store_id
        ).group_by(Inventory.inventory_type)
    )
    units: dict[str, int] = {row[0]: int(row[1] or 0) for row in units_q}

    # Recent outcomes (last 10 decided recommendations)
    recent_q = await db.execute(
        select(ManagerRecommendation).where(
            ManagerRecommendation.store_id == store_id,
            ManagerRecommendation.status.in_(["approved", "rejected", "applied"]),
        ).order_by(ManagerRecommendation.decided_at.desc()).limit(10)
    )
    recent_outcomes = [
        {
            "recommendationId": str(r.id),
            "skuId": str(r.sku_id) if r.sku_id else None,
            "title": r.title,
            "type": r.rec_type,
            "status": r.status,
            "updatedAt": r.decided_at.isoformat() if r.decided_at else None,
        }
        for r in recent_q.scalars()
    ]

    return DataResponse(data={
        "storeId": str(store_id),
        "analysisStatus": "ready",
        "lastGeneratedAt": None,
        "lowStockCount": low_stock_count,
        "anomalyCount": rec_counts.get("stock_anomaly", 0),
        "pendingPriceRecommendations": rec_counts.get("price_change", 0),
        "pendingReorderRecommendations": rec_counts.get("reorder", 0),
        "pendingStockAnomalies": rec_counts.get("stock_anomaly", 0),
        "openPurchaseOrders": open_po_count,
        "activeWorkOrders": active_wo_count,
        "inTransitTransfers": in_transit_count,
        "purchasedUnits": units.get("purchased", 0),
        "materialUnits": units.get("material", 0),
        "finishedUnits": units.get("finished", 0),
        "recentOutcomes": recent_outcomes,
    })


# ------------------------------------------------------------------ #
# GET /inventory                                                        #
# ------------------------------------------------------------------ #

@router.get("/inventory", response_model=DataResponse[list])
async def copilot_inventory(
    store_id: UUID,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    await _get_store_or_404(store_id, db)

    # Fetch inventories with SKU and optional supplier
    inv_q = await db.execute(
        select(Inventory, SKU).join(SKU, SKU.id == Inventory.sku_id).where(
            Inventory.store_id == store_id
        )
    )
    rows = inv_q.all()

    # Fetch active prices (valid today)
    from datetime import date
    today = date.today()
    price_q = await db.execute(
        select(Price).where(
            Price.store_id == store_id,
            Price.valid_from <= today,
            Price.valid_to >= today,
        )
    )
    prices_by_sku: dict[uuid.UUID, Price] = {p.sku_id: p for p in price_q.scalars()}

    # Fetch latest prices (any) for SKUs without active price
    any_price_q = await db.execute(
        select(Price).where(Price.store_id == store_id).order_by(Price.valid_to.desc())
    )
    any_price_by_sku: dict[uuid.UUID, Price] = {}
    for p in any_price_q.scalars():
        if p.sku_id not in any_price_by_sku:
            any_price_by_sku[p.sku_id] = p

    # Fetch supplier names
    supplier_ids = {inv.primary_supplier_id for inv, _ in rows if inv.primary_supplier_id}
    supplier_names: dict[uuid.UUID, str] = {}
    if supplier_ids:
        sup_q = await db.execute(select(Supplier).where(Supplier.id.in_(supplier_ids)))
        supplier_names = {s.id: s.name for s in sup_q.scalars()}

    # Pending recommendations per inventory
    rec_q = await db.execute(
        select(
            ManagerRecommendation.inventory_id,
            ManagerRecommendation.rec_type,
            func.count().label("cnt"),
        ).where(
            ManagerRecommendation.store_id == store_id,
            ManagerRecommendation.status == "pending",
            ManagerRecommendation.inventory_id.isnot(None),
        ).group_by(ManagerRecommendation.inventory_id, ManagerRecommendation.rec_type)
    )
    pending_by_inv: dict[uuid.UUID, dict[str, int]] = {}
    for inv_id, rec_type, cnt in rec_q:
        pending_by_inv.setdefault(inv_id, {})
        pending_by_inv[inv_id][rec_type] = cnt

    # Recent sales (last 30 days)
    from sqlalchemy import cast, Numeric as SQLNumeric
    thirty_days_ago = _now() - timedelta(days=30)
    sales_q = await db.execute(text("""
        SELECT oi.sku_id, SUM(oi.qty) AS total_qty, SUM(oi.line_total) AS total_rev
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE o.store_id = :store_id
          AND o.created_at >= :since
          AND o.status = 'completed'
        GROUP BY oi.sku_id
    """), {"store_id": str(store_id), "since": thirty_days_ago})
    sales_by_sku: dict[str, dict] = {
        str(r.sku_id): {"qty": int(r.total_qty or 0), "rev": float(r.total_rev or 0)}
        for r in sales_q
    }

    result = []
    for inv, sku in rows:
        active_price = prices_by_sku.get(sku.id) or any_price_by_sku.get(sku.id)
        pending = pending_by_inv.get(inv.id, {})
        sales = sales_by_sku.get(str(sku.id), {"qty": 0, "rev": 0.0})
        avg_daily = sales["qty"] / 30.0
        days_cover = (inv.qty_on_hand / avg_daily) if avg_daily > 0 else None

        result.append({
            "inventoryId": str(inv.id),
            "skuId": str(sku.id),
            "storeId": str(store_id),
            "skuCode": sku.sku_code,
            "description": sku.description,
            "longDescription": sku.long_description,
            "inventoryType": inv.inventory_type,
            "sourcingStrategy": inv.sourcing_strategy,
            "supplierName": supplier_names.get(inv.primary_supplier_id) if inv.primary_supplier_id else None,
            "costPrice": float(sku.cost_price) if sku.cost_price else None,
            "currentPrice": float(active_price.price_incl_tax) if active_price else None,
            "currentPriceValidUntil": active_price.valid_to.isoformat() if active_price else None,
            "purchasedQty": inv.qty_on_hand if inv.inventory_type == "purchased" else 0,
            "purchasedIncomingQty": 0,
            "materialQty": inv.qty_on_hand if inv.inventory_type == "material" else 0,
            "materialIncomingQty": 0,
            "materialAllocatedQty": 0,
            "finishedQty": inv.qty_on_hand if inv.inventory_type == "finished" else 0,
            "finishedAllocatedQty": 0,
            "inTransitQty": 0,
            "activeWorkOrderCount": 0,
            "qtyOnHand": inv.qty_on_hand,
            "reorderLevel": inv.reorder_level,
            "reorderQty": inv.reorder_qty,
            "lowStock": inv.qty_on_hand <= inv.reorder_level and inv.reorder_level > 0,
            "anomalyFlag": "stock_anomaly" in pending,
            "anomalyReason": "Stock anomaly detected" if "stock_anomaly" in pending else None,
            "recentSalesQty": sales["qty"],
            "recentSalesRevenue": sales["rev"],
            "avgDailySales": round(avg_daily, 2),
            "daysOfCover": round(days_cover, 1) if days_cover is not None else None,
            "pendingRecommendationCount": sum(pending.values()),
            "pendingPriceRecommendationCount": pending.get("price_change", 0),
            "lastUpdated": inv.last_updated.isoformat() if inv.last_updated else None,
        })

    return DataResponse(data=result)


# ------------------------------------------------------------------ #
# GET /recommendations                                                  #
# ------------------------------------------------------------------ #

@router.get("/recommendations", response_model=DataResponse[list])
async def copilot_recommendations(
    store_id: UUID,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    await _get_store_or_404(store_id, db)
    recs_q = await db.execute(
        select(ManagerRecommendation).where(
            ManagerRecommendation.store_id == store_id,
        ).order_by(ManagerRecommendation.generated_at.desc()).limit(200)
    )
    return DataResponse(data=[_rec_to_dict(r) for r in recs_q.scalars()])


# ------------------------------------------------------------------ #
# GET /adjustments                                                      #
# ------------------------------------------------------------------ #

@router.get("/adjustments", response_model=DataResponse[list])
async def copilot_adjustments(
    store_id: UUID,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    await _get_store_or_404(store_id, db)
    logs_q = await db.execute(
        select(InventoryAdjustmentLog).where(
            InventoryAdjustmentLog.store_id == store_id,
        ).order_by(InventoryAdjustmentLog.created_at.desc()).limit(100)
    )
    return DataResponse(data=[
        {
            "id": str(log.id),
            "inventoryId": str(log.inventory_id),
            "skuId": str(log.sku_id),
            "storeId": str(log.store_id),
            "quantityDelta": log.quantity_delta,
            "resultingQty": log.resulting_qty,
            "reason": log.reason,
            "source": log.source,
            "note": log.note,
            "createdAt": log.created_at.isoformat(),
        }
        for log in logs_q.scalars()
    ])


# ------------------------------------------------------------------ #
# POST /recommendations/analyze                                         #
# ------------------------------------------------------------------ #

class AnalyzeRequest(BaseModel):
    forceRefresh: bool = False
    lookbackDays: int = Field(30, ge=1, le=365)
    lowStockThreshold: int = Field(5, ge=0)


@router.post("/recommendations/analyze", response_model=DataResponse[dict])
async def analyze_recommendations(
    store_id: UUID,
    payload: AnalyzeRequest,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    await _get_store_or_404(store_id, db)
    now = _now()
    created = 0
    reused = 0

    # Fetch inventories + SKUs
    inv_q = await db.execute(
        select(Inventory, SKU).join(SKU, SKU.id == Inventory.sku_id).where(
            Inventory.store_id == store_id
        )
    )
    rows = inv_q.all()

    # Fetch supplier names
    supplier_ids = {inv.primary_supplier_id for inv, _ in rows if inv.primary_supplier_id}
    supplier_names: dict[uuid.UUID, str] = {}
    if supplier_ids:
        sup_q = await db.execute(select(Supplier).where(Supplier.id.in_(supplier_ids)))
        supplier_names = {s.id: s.name for s in sup_q.scalars()}

    # Get existing pending recommendations to avoid duplicates
    existing_q = await db.execute(
        select(ManagerRecommendation.inventory_id, ManagerRecommendation.rec_type).where(
            ManagerRecommendation.store_id == store_id,
            ManagerRecommendation.status == "pending",
        )
    )
    existing_pending: set[tuple] = {(str(r[0]), r[1]) for r in existing_q}

    # Fetch active prices
    from datetime import date
    today = date.today()
    price_q = await db.execute(
        select(Price).where(
            Price.store_id == store_id,
            Price.valid_to < today,  # expired prices
        )
    )
    expired_prices: set[uuid.UUID] = {p.sku_id for p in price_q.scalars()}

    new_recs = []
    for inv, sku in rows:
        key_reorder = (str(inv.id), "reorder")
        key_price = (str(inv.id), "price_change")
        key_anomaly = (str(inv.id), "stock_anomaly")

        supplier_name = supplier_names.get(inv.primary_supplier_id) if inv.primary_supplier_id else None
        workflow = "purchase_order" if inv.sourcing_strategy == "supplier_premade" else "work_order"

        # Rule 1: Low stock → reorder
        if inv.reorder_level > 0 and inv.qty_on_hand <= inv.reorder_level:
            if key_reorder not in existing_pending or payload.forceRefresh:
                if key_reorder in existing_pending:
                    reused += 1
                else:
                    qty = max(inv.reorder_qty, inv.reorder_level * 2)
                    rec = ManagerRecommendation(
                        id=uuid.uuid4(),
                        store_id=store_id,
                        sku_id=sku.id,
                        inventory_id=inv.id,
                        inventory_type=inv.inventory_type,
                        sourcing_strategy=inv.sourcing_strategy,
                        supplier_name=supplier_name,
                        rec_type="reorder",
                        status="pending",
                        title=f"Reorder {sku.description}",
                        rationale=(
                            f"Stock level ({inv.qty_on_hand} units) is at or below reorder level "
                            f"({inv.reorder_level} units)."
                        ),
                        confidence=0.95,
                        supporting_metrics={
                            "qty_on_hand": inv.qty_on_hand,
                            "reorder_level": inv.reorder_level,
                            "suggested_qty": qty,
                        },
                        source="rules_engine",
                        expected_impact=f"Replenish {qty} units to avoid stockout.",
                        suggested_order_qty=qty,
                        workflow_action=workflow,
                        analysis_status="complete",
                        generated_at=now,
                    )
                    new_recs.append(rec)
                    created += 1

        # Rule 2: Negative stock → anomaly
        if inv.qty_on_hand < 0:
            if key_anomaly not in existing_pending or payload.forceRefresh:
                if key_anomaly not in existing_pending:
                    rec = ManagerRecommendation(
                        id=uuid.uuid4(),
                        store_id=store_id,
                        sku_id=sku.id,
                        inventory_id=inv.id,
                        inventory_type=inv.inventory_type,
                        sourcing_strategy=inv.sourcing_strategy,
                        supplier_name=supplier_name,
                        rec_type="stock_anomaly",
                        status="pending",
                        title=f"Negative stock detected: {sku.description}",
                        rationale=f"Inventory shows {inv.qty_on_hand} units — negative stock requires investigation.",
                        confidence=1.0,
                        supporting_metrics={"qty_on_hand": inv.qty_on_hand},
                        source="rules_engine",
                        expected_impact="Investigate and correct stock count.",
                        workflow_action="price_review",
                        analysis_status="complete",
                        generated_at=now,
                    )
                    new_recs.append(rec)
                    created += 1

        # Rule 3: Expired price → price review
        if sku.id in expired_prices:
            if key_price not in existing_pending or payload.forceRefresh:
                if key_price not in existing_pending:
                    rec = ManagerRecommendation(
                        id=uuid.uuid4(),
                        store_id=store_id,
                        sku_id=sku.id,
                        inventory_id=inv.id,
                        inventory_type=inv.inventory_type,
                        sourcing_strategy=inv.sourcing_strategy,
                        supplier_name=supplier_name,
                        rec_type="price_change",
                        status="pending",
                        title=f"Price expired: {sku.description}",
                        rationale="The active price record has expired. Review and update pricing.",
                        confidence=0.9,
                        supporting_metrics={"cost_price": float(sku.cost_price or 0)},
                        source="rules_engine",
                        expected_impact="Ensure correct pricing at point of sale.",
                        workflow_action="price_review",
                        analysis_status="complete",
                        generated_at=now,
                    )
                    new_recs.append(rec)
                    created += 1

    db.add_all(new_recs)
    await db.flush()

    # Return all current recommendations
    all_recs_q = await db.execute(
        select(ManagerRecommendation).where(
            ManagerRecommendation.store_id == store_id,
        ).order_by(ManagerRecommendation.generated_at.desc()).limit(200)
    )
    all_recs = [_rec_to_dict(r) for r in all_recs_q.scalars()]

    return DataResponse(data={
        "analysisStatus": "complete",
        "multicaStatus": "complete",
        "recommendationsCreated": created,
        "recommendationsReused": reused,
        "recommendations": all_recs,
    })


# ------------------------------------------------------------------ #
# POST /recommendations/{rec_id}/approve|reject|apply                  #
# ------------------------------------------------------------------ #

class DecisionRequest(BaseModel):
    note: str = ""


async def _get_rec(rec_id: UUID, store_id: UUID, db: AsyncSession) -> ManagerRecommendation:
    result = await db.execute(
        select(ManagerRecommendation).where(
            ManagerRecommendation.id == rec_id,
            ManagerRecommendation.store_id == store_id,
        )
    )
    rec = result.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return rec


@router.post("/recommendations/{rec_id}/approve", response_model=DataResponse[dict])
async def approve_recommendation(
    store_id: UUID,
    rec_id: UUID,
    payload: DecisionRequest,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    rec = await _get_rec(rec_id, store_id, db)
    if rec.status not in ("pending", "queued"):
        raise HTTPException(status_code=400, detail=f"Cannot approve recommendation with status '{rec.status}'")
    rec.status = "approved"
    rec.decided_at = _now()
    rec.note = payload.note or rec.note
    await db.flush()
    return DataResponse(data=_rec_to_dict(rec))


@router.post("/recommendations/{rec_id}/reject", response_model=DataResponse[dict])
async def reject_recommendation(
    store_id: UUID,
    rec_id: UUID,
    payload: DecisionRequest,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    rec = await _get_rec(rec_id, store_id, db)
    if rec.status not in ("pending", "queued", "approved"):
        raise HTTPException(status_code=400, detail=f"Cannot reject recommendation with status '{rec.status}'")
    rec.status = "rejected"
    rec.decided_at = _now()
    rec.note = payload.note or rec.note
    await db.flush()
    return DataResponse(data=_rec_to_dict(rec))


@router.post("/recommendations/{rec_id}/apply", response_model=DataResponse[dict])
async def apply_recommendation(
    store_id: UUID,
    rec_id: UUID,
    payload: DecisionRequest,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    rec = await _get_rec(rec_id, store_id, db)
    if rec.status not in ("approved", "pending"):
        raise HTTPException(status_code=400, detail=f"Cannot apply recommendation with status '{rec.status}'")
    now = _now()
    rec.status = "applied"
    rec.decided_at = rec.decided_at or now
    rec.applied_at = now
    rec.note = payload.note or rec.note
    await db.flush()
    return DataResponse(data=_rec_to_dict(rec))
