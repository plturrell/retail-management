"""Supply Chain — purchase orders, work orders, stock transfers, and inventory stages.

Endpoints:
  GET  /api/stores/{store_id}/supply-chain/summary
  GET  /api/stores/{store_id}/supply-chain/stages
  GET  /api/stores/{store_id}/supply-chain/suppliers
  GET  /api/stores/{store_id}/supply-chain/purchase-orders
  GET  /api/stores/{store_id}/supply-chain/work-orders
  GET  /api/stores/{store_id}/supply-chain/transfers
  POST /api/stores/{store_id}/supply-chain/purchase-orders/{po_id}/receive
  POST /api/stores/{store_id}/supply-chain/work-orders/{wo_id}/start
  POST /api/stores/{store_id}/supply-chain/work-orders/{wo_id}/complete
  POST /api/stores/{store_id}/supply-chain/transfers/{transfer_id}/receive
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.inventory import Inventory
from app.models.supplier import Supplier
from app.models.purchase import (
    PurchaseOrder,
    PurchaseOrderStatus,
)
from app.models.copilot import (
    WorkOrder,
    WorkOrderStatus,
    StockTransfer,
    StockTransferStatus,
)
from app.models.user import UserStoreRole, RoleEnum
from app.auth.dependencies import require_store_role
from app.schemas.common import DataResponse

router = APIRouter(
    prefix="/api/stores/{store_id}/supply-chain",
    tags=["supply-chain"],
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ------------------------------------------------------------------ #
# Request bodies                                                       #
# ------------------------------------------------------------------ #

class ReceivePOBody(BaseModel):
    items: list[dict] = Field(default_factory=list, description="[{skuId, qtyReceived}]")
    note: Optional[str] = None


class StartWorkOrderBody(BaseModel):
    note: Optional[str] = None


class CompleteWorkOrderBody(BaseModel):
    completedQuantity: int
    note: Optional[str] = None


class ReceiveTransferBody(BaseModel):
    note: Optional[str] = None


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _wo_to_dict(wo: WorkOrder) -> dict:
    return {
        "id": str(wo.id),
        "storeId": str(wo.store_id),
        "finishedSkuId": str(wo.finished_sku_id),
        "workOrderType": wo.work_order_type,
        "status": wo.status if isinstance(wo.status, str) else wo.status.value,
        "targetQuantity": wo.target_quantity,
        "completedQuantity": wo.completed_quantity,
        "dueDate": wo.due_date.isoformat() if wo.due_date else None,
        "note": wo.note,
        "recommendationId": str(wo.recommendation_id) if wo.recommendation_id else None,
        "components": [
            {
                "id": str(c.id),
                "skuId": str(c.sku_id),
                "quantityRequired": c.quantity_required,
                "note": c.note,
            }
            for c in (wo.components or [])
        ],
        "createdAt": wo.created_at.isoformat() if wo.created_at else None,
        "updatedAt": wo.updated_at.isoformat() if wo.updated_at else None,
    }


def _transfer_to_dict(t: StockTransfer) -> dict:
    return {
        "id": str(t.id),
        "storeId": str(t.store_id),
        "skuId": str(t.sku_id),
        "quantity": t.quantity,
        "fromInventoryType": t.from_inventory_type if isinstance(t.from_inventory_type, str) else t.from_inventory_type.value,
        "toInventoryType": t.to_inventory_type if isinstance(t.to_inventory_type, str) else t.to_inventory_type.value,
        "status": t.status if isinstance(t.status, str) else t.status.value,
        "note": t.note,
        "recommendationId": str(t.recommendation_id) if t.recommendation_id else None,
        "dispatchedAt": t.dispatched_at.isoformat() if t.dispatched_at else None,
        "receivedAt": t.received_at.isoformat() if t.received_at else None,
        "createdAt": t.created_at.isoformat() if t.created_at else None,
        "updatedAt": t.updated_at.isoformat() if t.updated_at else None,
    }


def _po_to_dict(po: PurchaseOrder) -> dict:
    return {
        "id": str(po.id),
        "poNumber": po.po_number,
        "storeId": str(po.store_id),
        "supplierId": str(po.supplier_id),
        "orderDate": po.order_date.isoformat() if po.order_date else None,
        "expectedDeliveryDate": po.expected_delivery_date.isoformat() if po.expected_delivery_date else None,
        "status": po.status if isinstance(po.status, str) else po.status.value,
        "subtotal": float(po.subtotal),
        "taxTotal": float(po.tax_total),
        "grandTotal": float(po.grand_total),
        "currency": po.currency,
        "notes": po.notes,
        "createdAt": po.created_at.isoformat() if po.created_at else None,
        "updatedAt": po.updated_at.isoformat() if po.updated_at else None,
    }


# ------------------------------------------------------------------ #
# GET /summary                                                         #
# ------------------------------------------------------------------ #

@router.get("/summary", response_model=DataResponse)
async def supply_chain_summary(
    store_id: UUID,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.staff)),
    db: AsyncSession = Depends(get_db),
):
    """High-level supply chain KPIs for the store dashboard."""

    # Open POs
    open_pos_q = await db.execute(
        select(func.count()).select_from(PurchaseOrder).where(
            and_(
                PurchaseOrder.store_id == store_id,
                PurchaseOrder.status.in_([
                    PurchaseOrderStatus.submitted,
                    PurchaseOrderStatus.confirmed,
                    PurchaseOrderStatus.partially_received,
                ]),
            )
        )
    )
    open_pos = open_pos_q.scalar() or 0

    # Active work orders
    active_wos_q = await db.execute(
        select(func.count()).select_from(WorkOrder).where(
            and_(
                WorkOrder.store_id == store_id,
                WorkOrder.status.in_([WorkOrderStatus.scheduled, WorkOrderStatus.in_progress]),
            )
        )
    )
    active_work_orders = active_wos_q.scalar() or 0

    # In-transit transfers
    in_transit_q = await db.execute(
        select(func.count()).select_from(StockTransfer).where(
            and_(
                StockTransfer.store_id == store_id,
                StockTransfer.status == StockTransferStatus.in_transit,
            )
        )
    )
    in_transit_transfers = in_transit_q.scalar() or 0

    # Inventory breakdown by type
    inv_breakdown_q = await db.execute(
        select(Inventory.inventory_type, func.sum(Inventory.qty_on_hand))
        .where(Inventory.store_id == store_id)
        .group_by(Inventory.inventory_type)
    )
    inv_by_type: dict[str, int] = {}
    for row in inv_breakdown_q.all():
        inv_by_type[str(row[0])] = int(row[1] or 0)

    # Low stock items (qty_on_hand <= reorder_level, with reorder threshold set)
    low_stock_q = await db.execute(
        select(func.count()).select_from(Inventory).where(
            and_(
                Inventory.store_id == store_id,
                Inventory.qty_on_hand <= Inventory.reorder_level,
                Inventory.reorder_level > 0,
            )
        )
    )
    low_stock_count = low_stock_q.scalar() or 0

    return DataResponse(
        success=True,
        message="Supply chain summary",
        data={
            "openPurchaseOrders": open_pos,
            "activeWorkOrders": active_work_orders,
            "inTransitTransfers": in_transit_transfers,
            "lowStockItems": low_stock_count,
            "inventoryByType": {
                "purchased": inv_by_type.get("purchased", 0),
                "material": inv_by_type.get("material", 0),
                "finished": inv_by_type.get("finished", 0),
            },
        },
    )


# ------------------------------------------------------------------ #
# GET /stages                                                          #
# ------------------------------------------------------------------ #

@router.get("/stages", response_model=DataResponse)
async def inventory_stages(
    store_id: UUID,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.staff)),
    db: AsyncSession = Depends(get_db),
):
    """Inventory grouped by stage (purchased / material / finished) with per-stage totals."""

    rows_q = await db.execute(
        select(
            Inventory.inventory_type,
            Inventory.sourcing_strategy,
            func.count(Inventory.id).label("sku_count"),
            func.sum(Inventory.qty_on_hand).label("total_qty"),
        )
        .where(Inventory.store_id == store_id)
        .group_by(Inventory.inventory_type, Inventory.sourcing_strategy)
    )

    stages: dict[str, Any] = {}
    for row in rows_q.all():
        inv_type = str(row[0])
        sourcing = str(row[1])
        if inv_type not in stages:
            stages[inv_type] = {
                "inventoryType": inv_type,
                "totalSkus": 0,
                "totalQty": 0,
                "sourcingBreakdown": {},
            }
        stages[inv_type]["totalSkus"] += int(row[2] or 0)
        stages[inv_type]["totalQty"] += int(row[3] or 0)
        stages[inv_type]["sourcingBreakdown"][sourcing] = int(row[2] or 0)

    return DataResponse(
        success=True,
        message="Inventory stages",
        data={"stages": list(stages.values())},
    )


# ------------------------------------------------------------------ #
# GET /suppliers                                                       #
# ------------------------------------------------------------------ #

@router.get("/suppliers", response_model=DataResponse)
async def supply_chain_suppliers(
    store_id: UUID,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.staff)),
    db: AsyncSession = Depends(get_db),
):
    """Suppliers that have POs or are set as primary on inventory for this store."""

    po_supplier_ids_q = await db.execute(
        select(PurchaseOrder.supplier_id).where(PurchaseOrder.store_id == store_id).distinct()
    )
    po_supplier_ids = {r[0] for r in po_supplier_ids_q.all()}

    inv_supplier_ids_q = await db.execute(
        select(Inventory.primary_supplier_id).where(
            and_(Inventory.store_id == store_id, Inventory.primary_supplier_id.isnot(None))
        ).distinct()
    )
    inv_supplier_ids = {r[0] for r in inv_supplier_ids_q.all()}

    all_ids = po_supplier_ids | inv_supplier_ids
    if not all_ids:
        return DataResponse(success=True, message="Suppliers", data={"suppliers": []})

    suppliers_q = await db.execute(
        select(Supplier).where(Supplier.id.in_(all_ids)).order_by(Supplier.name)
    )
    suppliers = suppliers_q.scalars().all()

    return DataResponse(
        success=True,
        message="Suppliers",
        data={
            "suppliers": [
                {
                    "id": str(s.id),
                    "supplierCode": s.supplier_code,
                    "name": s.name,
                    "contactPerson": s.contact_person,
                    "email": s.email,
                    "phone": s.phone,
                    "country": s.country,
                    "currency": s.currency,
                    "paymentTermsDays": s.payment_terms_days,
                    "isActive": s.is_active,
                }
                for s in suppliers
            ]
        },
    )


# ------------------------------------------------------------------ #
# GET /purchase-orders                                                 #
# ------------------------------------------------------------------ #

@router.get("/purchase-orders", response_model=DataResponse)
async def supply_chain_purchase_orders(
    store_id: UUID,
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _: UserStoreRole = Depends(require_store_role(RoleEnum.staff)),
    db: AsyncSession = Depends(get_db),
):
    """List purchase orders for this store, newest first."""

    q = select(PurchaseOrder).where(PurchaseOrder.store_id == store_id)
    if status:
        try:
            q = q.where(PurchaseOrder.status == PurchaseOrderStatus(status))
        except ValueError:
            pass
    q = q.order_by(PurchaseOrder.created_at.desc()).limit(limit)

    result = await db.execute(q)
    pos = result.scalars().all()

    return DataResponse(
        success=True,
        message="Purchase orders",
        data={"purchaseOrders": [_po_to_dict(po) for po in pos]},
    )


# ------------------------------------------------------------------ #
# GET /work-orders                                                     #
# ------------------------------------------------------------------ #

@router.get("/work-orders", response_model=DataResponse)
async def supply_chain_work_orders(
    store_id: UUID,
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _: UserStoreRole = Depends(require_store_role(RoleEnum.staff)),
    db: AsyncSession = Depends(get_db),
):
    """List work orders for this store."""

    q = select(WorkOrder).where(WorkOrder.store_id == store_id)
    if status:
        try:
            q = q.where(WorkOrder.status == WorkOrderStatus(status))
        except ValueError:
            pass
    q = q.order_by(WorkOrder.created_at.desc()).limit(limit)

    result = await db.execute(q)
    wos = result.scalars().all()

    return DataResponse(
        success=True,
        message="Work orders",
        data={"workOrders": [_wo_to_dict(wo) for wo in wos]},
    )


# ------------------------------------------------------------------ #
# GET /transfers                                                       #
# ------------------------------------------------------------------ #

@router.get("/transfers", response_model=DataResponse)
async def supply_chain_transfers(
    store_id: UUID,
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _: UserStoreRole = Depends(require_store_role(RoleEnum.staff)),
    db: AsyncSession = Depends(get_db),
):
    """List stock transfers for this store."""

    q = select(StockTransfer).where(StockTransfer.store_id == store_id)
    if status:
        try:
            q = q.where(StockTransfer.status == StockTransferStatus(status))
        except ValueError:
            pass
    q = q.order_by(StockTransfer.created_at.desc()).limit(limit)

    result = await db.execute(q)
    transfers = result.scalars().all()

    return DataResponse(
        success=True,
        message="Stock transfers",
        data={"transfers": [_transfer_to_dict(t) for t in transfers]},
    )


# ------------------------------------------------------------------ #
# POST /purchase-orders/{po_id}/receive                               #
# ------------------------------------------------------------------ #

@router.post("/purchase-orders/{po_id}/receive", response_model=DataResponse)
async def receive_purchase_order(
    store_id: UUID,
    po_id: UUID,
    body: ReceivePOBody,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    """Record goods received against a PO and update inventory quantities."""

    po_q = await db.execute(
        select(PurchaseOrder).where(
            and_(PurchaseOrder.id == po_id, PurchaseOrder.store_id == store_id)
        )
    )
    po = po_q.scalar_one_or_none()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if po.status in [PurchaseOrderStatus.fully_received, PurchaseOrderStatus.cancelled]:
        raise HTTPException(status_code=400, detail=f"PO is {po.status.value}, cannot receive")

    now = _now()
    received_items: list[dict] = []

    for item_data in body.items:
        # Accept both camelCase and snake_case field names
        sku_id_raw = item_data.get("skuId") or item_data.get("sku_id")
        qty = int(item_data.get("qtyReceived") or item_data.get("qty_received") or 0)
        if not sku_id_raw or qty <= 0:
            continue
        sku_id = UUID(str(sku_id_raw))

        # Update or create inventory record
        inv_q = await db.execute(
            select(Inventory).where(
                and_(Inventory.store_id == store_id, Inventory.sku_id == sku_id)
            )
        )
        inv = inv_q.scalar_one_or_none()
        if inv:
            inv.qty_on_hand += qty
            inv.last_updated = now
            inv.updated_at = now
        else:
            inv = Inventory(
                id=uuid.uuid4(),
                store_id=store_id,
                sku_id=sku_id,
                qty_on_hand=qty,
                reorder_level=0,
                reorder_qty=0,
                last_updated=now,
                primary_supplier_id=po.supplier_id,
            )
            db.add(inv)

        received_items.append({"skuId": str(sku_id), "qtyReceived": qty})

    po.status = PurchaseOrderStatus.fully_received
    po.updated_at = now
    await db.commit()

    return DataResponse(
        success=True,
        message="Goods received and inventory updated",
        data={"poId": str(po_id), "itemsReceived": received_items},
    )


# ------------------------------------------------------------------ #
# POST /work-orders/{wo_id}/start                                     #
# ------------------------------------------------------------------ #

@router.post("/work-orders/{wo_id}/start", response_model=DataResponse)
async def start_work_order(
    store_id: UUID,
    wo_id: UUID,
    body: StartWorkOrderBody,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    """Transition a work order from scheduled → in_progress and deduct component materials."""

    wo_q = await db.execute(
        select(WorkOrder).where(and_(WorkOrder.id == wo_id, WorkOrder.store_id == store_id))
    )
    wo = wo_q.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")

    wo_status = wo.status if isinstance(wo.status, str) else wo.status.value
    if wo_status != "scheduled":
        raise HTTPException(status_code=400, detail=f"Work order is '{wo_status}', expected 'scheduled'")

    now = _now()

    # Deduct component materials from inventory
    for component in wo.components:
        inv_q = await db.execute(
            select(Inventory).where(
                and_(Inventory.store_id == store_id, Inventory.sku_id == component.sku_id)
            )
        )
        inv = inv_q.scalar_one_or_none()
        if inv:
            inv.qty_on_hand = max(0, inv.qty_on_hand - component.quantity_required)
            inv.last_updated = now
            inv.updated_at = now

    wo.status = "in_progress"
    if body.note:
        wo.note = body.note
    wo.updated_at = now
    await db.commit()

    return DataResponse(success=True, message="Work order started", data=_wo_to_dict(wo))


# ------------------------------------------------------------------ #
# POST /work-orders/{wo_id}/complete                                  #
# ------------------------------------------------------------------ #

@router.post("/work-orders/{wo_id}/complete", response_model=DataResponse)
async def complete_work_order(
    store_id: UUID,
    wo_id: UUID,
    body: CompleteWorkOrderBody,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    """Mark work order complete and add finished goods to finished inventory."""

    wo_q = await db.execute(
        select(WorkOrder).where(and_(WorkOrder.id == wo_id, WorkOrder.store_id == store_id))
    )
    wo = wo_q.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")

    wo_status = wo.status if isinstance(wo.status, str) else wo.status.value
    if wo_status != "in_progress":
        raise HTTPException(status_code=400, detail=f"Work order is '{wo_status}', expected 'in_progress'")
    if body.completedQuantity <= 0:
        raise HTTPException(status_code=400, detail="completedQuantity must be > 0")

    now = _now()

    # Add completed quantity to finished inventory
    inv_q = await db.execute(
        select(Inventory).where(
            and_(Inventory.store_id == store_id, Inventory.sku_id == wo.finished_sku_id)
        )
    )
    inv = inv_q.scalar_one_or_none()
    if inv:
        inv.qty_on_hand += body.completedQuantity
        inv.inventory_type = "finished"
        inv.last_updated = now
        inv.updated_at = now
    else:
        inv = Inventory(
            id=uuid.uuid4(),
            store_id=store_id,
            sku_id=wo.finished_sku_id,
            qty_on_hand=body.completedQuantity,
            reorder_level=0,
            reorder_qty=0,
            inventory_type="finished",
            last_updated=now,
        )
        db.add(inv)

    wo.completed_quantity = body.completedQuantity
    wo.status = "completed"
    if body.note:
        wo.note = body.note
    wo.updated_at = now
    await db.commit()

    return DataResponse(success=True, message="Work order completed", data=_wo_to_dict(wo))


# ------------------------------------------------------------------ #
# POST /transfers/{transfer_id}/receive                               #
# ------------------------------------------------------------------ #

@router.post("/transfers/{transfer_id}/receive", response_model=DataResponse)
async def receive_transfer(
    store_id: UUID,
    transfer_id: UUID,
    body: ReceiveTransferBody,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.staff)),
    db: AsyncSession = Depends(get_db),
):
    """Mark a stock transfer as received and update the inventory type."""

    t_q = await db.execute(
        select(StockTransfer).where(
            and_(StockTransfer.id == transfer_id, StockTransfer.store_id == store_id)
        )
    )
    transfer = t_q.scalar_one_or_none()
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer not found")

    t_status = transfer.status if isinstance(transfer.status, str) else transfer.status.value
    if t_status == "received":
        raise HTTPException(status_code=400, detail="Transfer already received")
    if t_status == "cancelled":
        raise HTTPException(status_code=400, detail="Transfer is cancelled")

    now = _now()
    to_type = transfer.to_inventory_type if isinstance(transfer.to_inventory_type, str) else transfer.to_inventory_type.value

    # Update inventory type to reflect the destination stage
    inv_q = await db.execute(
        select(Inventory).where(
            and_(Inventory.store_id == store_id, Inventory.sku_id == transfer.sku_id)
        )
    )
    inv = inv_q.scalar_one_or_none()
    if inv:
        inv.inventory_type = to_type
        inv.last_updated = now
        inv.updated_at = now

    transfer.status = "received"
    transfer.received_at = now
    if body.note:
        transfer.note = body.note
    transfer.updated_at = now
    await db.commit()

    return DataResponse(success=True, message="Transfer received", data=_transfer_to_dict(transfer))
