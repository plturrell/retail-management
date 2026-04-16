"""Supplier Portal — comprehensive supplier management with AI analytics.

Endpoints:
  GET  /api/suppliers/{id}/dashboard        Full supplier overview + metrics
  GET  /api/suppliers/{id}/catalog           Product catalog (from POs + supplier_products)
  GET  /api/suppliers/{id}/purchase-orders   PO list with status breakdown
  GET  /api/suppliers/{id}/analytics         AI-powered purchase & sell-through analytics
  GET  /api/suppliers/{id}/documents         List scanned order documents
  POST /api/suppliers/{id}/documents         Upload scanned order document
"""
from __future__ import annotations

import json
import logging
import uuid as uuid_mod
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import case, cast, func, select, Float
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.auth.dependencies import get_current_user
from app.models.supplier import Supplier, SupplierProduct
from app.models.purchase import PurchaseOrder, PurchaseOrderItem, PurchaseOrderStatus
from app.models.inventory import SKU, Inventory, Category
from app.models.order import Order, OrderItem, OrderStatus
from app.models.user import User
from app.schemas.common import DataResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/suppliers", tags=["supplier-portal"])


# ------------------------------------------------------------------ #
# Helpers                                                               #
# ------------------------------------------------------------------ #

def _dec(val) -> float:
    """Safely convert Decimal/None to float."""
    if val is None:
        return 0.0
    return float(val)


def _supplier_dict(s: Supplier) -> dict:
    return {
        "id": str(s.id),
        "supplierCode": s.supplier_code,
        "name": s.name,
        "contactPerson": s.contact_person,
        "email": s.email,
        "phone": s.phone,
        "address": s.address,
        "country": s.country,
        "currency": s.currency,
        "paymentTermsDays": s.payment_terms_days,
        "gstRegistered": s.gst_registered,
        "gstNumber": s.gst_number,
        "bankAccount": s.bank_account,
        "bankName": s.bank_name,
        "notes": s.notes,
        "isActive": s.is_active,
        "createdAt": s.created_at.isoformat() if s.created_at else None,
        "updatedAt": s.updated_at.isoformat() if s.updated_at else None,
    }


# ------------------------------------------------------------------ #
# 1. DASHBOARD — full supplier overview                                #
# ------------------------------------------------------------------ #

@router.get("/{supplier_id}/dashboard")
async def supplier_dashboard(
    supplier_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full supplier overview: details, PO summary, spend, product count, locations."""
    # Supplier
    result = await db.execute(select(Supplier).where(Supplier.id == supplier_id))
    supplier = result.scalar_one_or_none()
    if not supplier:
        raise HTTPException(404, "Supplier not found")

    # PO aggregates
    po_stats = await db.execute(
        select(
            func.count(PurchaseOrder.id).label("total_pos"),
            func.sum(PurchaseOrder.grand_total).label("total_spend"),
            func.min(PurchaseOrder.order_date).label("first_order"),
            func.max(PurchaseOrder.order_date).label("last_order"),
        ).where(PurchaseOrder.supplier_id == supplier_id)
    )
    stats = po_stats.one()

    # PO status breakdown
    status_rows = await db.execute(
        select(
            PurchaseOrder.status,
            func.count(PurchaseOrder.id),
            func.sum(PurchaseOrder.grand_total),
        )
        .where(PurchaseOrder.supplier_id == supplier_id)
        .group_by(PurchaseOrder.status)
    )
    status_breakdown = [
        {"status": row[0].value, "count": row[1], "totalSpend": _dec(row[2])}
        for row in status_rows.all()
    ]

    # Product count (unique SKUs from supplier_products)
    product_count = await db.execute(
        select(func.count(SupplierProduct.id))
        .where(SupplierProduct.supplier_id == supplier_id)
    )

    # Unique SKUs from PO line items
    po_sku_count = await db.execute(
        select(func.count(func.distinct(PurchaseOrderItem.sku_id)))
        .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .where(PurchaseOrder.supplier_id == supplier_id)
    )

    # Total qty purchased
    total_qty = await db.execute(
        select(func.sum(PurchaseOrderItem.qty_ordered))
        .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .where(PurchaseOrder.supplier_id == supplier_id)
    )

    # Inventory locations for this supplier's products
    inv_locations = await db.execute(
        select(
            Inventory.location_status,
            func.count(Inventory.id),
            func.sum(Inventory.qty_on_hand),
        )
        .join(SupplierProduct, SupplierProduct.sku_id == Inventory.sku_id)
        .where(SupplierProduct.supplier_id == supplier_id)
        .group_by(Inventory.location_status)
    )
    locations = [
        {"location": row[0].value if hasattr(row[0], 'value') else str(row[0]), "skuCount": row[1], "totalQty": row[2] or 0}
        for row in inv_locations.all()
    ]

    return DataResponse(data={
        "supplier": _supplier_dict(supplier),
        "metrics": {
            "totalPurchaseOrders": stats.total_pos or 0,
            "totalSpendSGD": _dec(stats.total_spend),
            "firstOrderDate": stats.first_order.isoformat() if stats.first_order else None,
            "lastOrderDate": stats.last_order.isoformat() if stats.last_order else None,
            "catalogProductCount": product_count.scalar() or 0,
            "poSkuCount": po_sku_count.scalar() or 0,
            "totalQtyPurchased": total_qty.scalar() or 0,
        },
        "statusBreakdown": status_breakdown,
        "inventoryLocations": locations,
    })


# ------------------------------------------------------------------ #
# 2. CATALOG — product catalog from POs + supplier_products            #
# ------------------------------------------------------------------ #

@router.get("/{supplier_id}/catalog")
async def supplier_catalog(
    supplier_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Product catalog: all SKUs linked to this supplier, with cost, inventory, and sell-through.

    Returns BOTH codes so the client can reconcile with supplier paperwork:
      * ``internalSkuCode`` — our own hierarchical code (e.g. ``DEC-CRY-000001``)
      * ``supplierSkuCode`` — the supplier's own code (e.g. ``A361black/brown``)
    ``skuCode`` is retained as an alias of ``internalSkuCode`` for backwards
    compatibility with existing clients.
    """
    # Verify supplier exists
    result = await db.execute(select(Supplier.id).where(Supplier.id == supplier_id))
    if not result.scalar_one_or_none():
        raise HTTPException(404, "Supplier not found")

    # Get all supplier products with SKU details — include parent category path
    # by doing two passes: first grab rows, then resolve parent names.
    sp_rows = await db.execute(
        select(
            SupplierProduct,
            SKU.sku_code,
            SKU.description,
            SKU.long_description,
            SKU.cost_price,
            SKU.is_unique_piece,
            SKU.product_type,
            SKU.attributes,
            SKU.status,
            SKU.category_id,
            Category.description.label("category_name"),
            Category.parent_id.label("parent_category_id"),
        )
        .join(SKU, SupplierProduct.sku_id == SKU.id)
        .outerjoin(Category, SKU.category_id == Category.id)
        .where(SupplierProduct.supplier_id == supplier_id)
        .order_by(SKU.sku_code)
    )

    # Resolve parent category names in one query
    rows = sp_rows.all()
    parent_ids = {row.parent_category_id for row in rows if row.parent_category_id}
    parent_name_map: dict[str, str] = {}
    if parent_ids:
        parent_rows = await db.execute(
            select(Category.id, Category.description).where(Category.id.in_(parent_ids))
        )
        parent_name_map = {str(cid): desc for cid, desc in parent_rows.all()}

    products = []
    sku_ids = []
    for row in rows:
        sp = row.SupplierProduct
        sku_ids.append(sp.sku_id)
        product_type_val = (
            row.product_type.value if hasattr(row.product_type, "value") else row.product_type
        )
        parent_name = parent_name_map.get(str(row.parent_category_id)) if row.parent_category_id else None
        category_path = [n for n in (parent_name, row.category_name) if n]
        products.append({
            "supplierProductId": str(sp.id),
            "skuId": str(sp.sku_id),
            "internalSkuCode": row.sku_code,
            "skuCode": row.sku_code,  # alias, retained for compatibility
            "supplierSkuCode": sp.supplier_sku_code,
            "description": row.description,
            "longDescription": row.long_description,
            "productType": product_type_val,
            "attributes": row.attributes or {},
            "status": row.status,
            "category": row.category_name,
            "categoryPath": category_path,
            "isUniquePiece": row.is_unique_piece,
            "supplierUnitCost": _dec(sp.supplier_unit_cost),
            "supplierCurrency": sp.currency,
            "costPriceSGD": _dec(row.cost_price),
            "minOrderQty": sp.min_order_qty,
            "leadTimeDays": sp.lead_time_days,
            "isPreferred": sp.is_preferred,
        })

    # Get inventory for all these SKUs
    if sku_ids:
        inv_rows = await db.execute(
            select(
                Inventory.sku_id,
                Inventory.qty_on_hand,
                Inventory.location_status,
                Inventory.reorder_level,
            ).where(Inventory.sku_id.in_(sku_ids))
        )
        inv_map: dict[str, dict] = {}
        for row in inv_rows.all():
            sid = str(row.sku_id)
            loc = row.location_status.value if hasattr(row.location_status, 'value') else str(row.location_status)
            inv_map[sid] = {
                "qtyOnHand": row.qty_on_hand,
                "location": loc,
                "reorderLevel": row.reorder_level,
                "lowStock": row.qty_on_hand <= row.reorder_level,
            }

        # Get sell-through data (completed orders) for these SKUs
        sell_rows = await db.execute(
            select(
                OrderItem.sku_id,
                func.sum(OrderItem.qty).label("qty_sold"),
                func.sum(OrderItem.line_total).label("revenue"),
                func.count(func.distinct(OrderItem.order_id)).label("order_count"),
                func.min(Order.order_date).label("first_sale"),
                func.max(Order.order_date).label("last_sale"),
            )
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                OrderItem.sku_id.in_(sku_ids),
                Order.status == OrderStatus.completed,
            )
            .group_by(OrderItem.sku_id)
        )
        sell_map: dict[str, dict] = {}
        for row in sell_rows.all():
            sid = str(row.sku_id)
            sell_map[sid] = {
                "qtySold": row.qty_sold or 0,
                "revenue": _dec(row.revenue),
                "orderCount": row.order_count or 0,
                "firstSale": row.first_sale.isoformat() if row.first_sale else None,
                "lastSale": row.last_sale.isoformat() if row.last_sale else None,
            }

        # Enrich products with inventory + sell-through
        for p in products:
            sid = p["skuId"]
            p["inventory"] = inv_map.get(sid, {"qtyOnHand": 0, "location": "UNKNOWN", "reorderLevel": 0, "lowStock": True})
            sell = sell_map.get(sid, {"qtySold": 0, "revenue": 0, "orderCount": 0, "firstSale": None, "lastSale": None})
            p["sellThrough"] = sell

            # Calculate margin if we have cost and revenue
            if sell["qtySold"] > 0 and p["costPriceSGD"] > 0:
                avg_selling_price = sell["revenue"] / sell["qtySold"]
                margin = ((avg_selling_price - p["costPriceSGD"]) / avg_selling_price) * 100
                p["sellThrough"]["avgSellingPrice"] = round(avg_selling_price, 2)
                p["sellThrough"]["marginPercent"] = round(margin, 1)
            else:
                p["sellThrough"]["avgSellingPrice"] = None
                p["sellThrough"]["marginPercent"] = None

    return DataResponse(data={
        "totalProducts": len(products),
        "products": products,
    })


# ------------------------------------------------------------------ #
# 2b. PROXY CATALOG — derived from PO history                           #
# ------------------------------------------------------------------ #

@router.get("/{supplier_id}/proxy-catalog")
async def supplier_proxy_catalog(
    supplier_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Derived catalog for suppliers without a formal product list.

    Aggregates every distinct SKU we have ever purchased from this supplier —
    with total qty ordered, average unit cost, first/last order dates, and
    current inventory. Useful when the supplier has no digital catalog: our
    purchase history *becomes* their catalog.
    """
    result = await db.execute(select(Supplier).where(Supplier.id == supplier_id))
    supplier = result.scalar_one_or_none()
    if not supplier:
        raise HTTPException(404, "Supplier not found")

    agg = await db.execute(
        select(
            PurchaseOrderItem.sku_id,
            SKU.sku_code,
            SKU.description,
            SKU.long_description,
            SKU.product_type,
            SKU.attributes,
            SKU.status,
            Category.description.label("category_name"),
            func.sum(PurchaseOrderItem.qty_ordered).label("total_qty_ordered"),
            func.sum(PurchaseOrderItem.line_total).label("total_spend"),
            func.avg(PurchaseOrderItem.unit_cost).label("avg_unit_cost"),
            func.count(func.distinct(PurchaseOrderItem.purchase_order_id)).label("po_count"),
            func.min(PurchaseOrder.order_date).label("first_ordered"),
            func.max(PurchaseOrder.order_date).label("last_ordered"),
        )
        .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .join(SKU, PurchaseOrderItem.sku_id == SKU.id)
        .outerjoin(Category, SKU.category_id == Category.id)
        .where(PurchaseOrder.supplier_id == supplier_id)
        .group_by(
            PurchaseOrderItem.sku_id,
            SKU.sku_code, SKU.description, SKU.long_description,
            SKU.product_type, SKU.attributes, SKU.status,
            Category.description,
        )
        .order_by(func.max(PurchaseOrder.order_date).desc())
    )
    rows = agg.all()

    # Supplier code map — one SKU can have multiple SupplierProduct entries,
    # we pick the preferred one or the first.
    sku_ids = [r.sku_id for r in rows]
    sp_map: dict[str, str] = {}
    if sku_ids:
        sp_rows = await db.execute(
            select(SupplierProduct.sku_id, SupplierProduct.supplier_sku_code)
            .where(
                SupplierProduct.supplier_id == supplier_id,
                SupplierProduct.sku_id.in_(sku_ids),
            )
            .order_by(SupplierProduct.is_preferred.desc())
        )
        for sid, code in sp_rows.all():
            sp_map.setdefault(str(sid), code)

    # Inventory map
    inv_map: dict[str, int] = {}
    if sku_ids:
        inv_rows = await db.execute(
            select(Inventory.sku_id, func.sum(Inventory.qty_on_hand))
            .where(Inventory.sku_id.in_(sku_ids))
            .group_by(Inventory.sku_id)
        )
        inv_map = {str(sid): int(qty or 0) for sid, qty in inv_rows.all()}

    products = []
    for r in rows:
        product_type_val = (
            r.product_type.value if hasattr(r.product_type, "value") else r.product_type
        )
        products.append({
            "skuId": str(r.sku_id),
            "internalSkuCode": r.sku_code,
            "skuCode": r.sku_code,
            "supplierSkuCode": sp_map.get(str(r.sku_id)),
            "description": r.description,
            "longDescription": r.long_description,
            "productType": product_type_val,
            "attributes": r.attributes or {},
            "status": r.status,
            "category": r.category_name,
            "totalQtyOrdered": int(r.total_qty_ordered or 0),
            "totalSpend": _dec(r.total_spend),
            "avgUnitCost": _dec(r.avg_unit_cost),
            "poCount": int(r.po_count or 0),
            "firstOrdered": r.first_ordered.isoformat() if r.first_ordered else None,
            "lastOrdered": r.last_ordered.isoformat() if r.last_ordered else None,
            "currentInventory": inv_map.get(str(r.sku_id), 0),
        })

    return DataResponse(data={
        "supplierId": str(supplier.id),
        "supplierCode": supplier.supplier_code,
        "supplierName": supplier.name,
        "supplierCurrency": supplier.currency,
        "source": "derived_from_purchase_orders",
        "totalProducts": len(products),
        "products": products,
    })


# ------------------------------------------------------------------ #
# 3. PURCHASE ORDERS — full PO list with line items                    #
# ------------------------------------------------------------------ #

@router.get("/{supplier_id}/purchase-orders")
async def supplier_purchase_orders(
    supplier_id: UUID,
    status: Optional[str] = Query(None),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """All POs for this supplier with line items and status."""
    result = await db.execute(select(Supplier.id).where(Supplier.id == supplier_id))
    if not result.scalar_one_or_none():
        raise HTTPException(404, "Supplier not found")

    q = (
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.items))
        .where(PurchaseOrder.supplier_id == supplier_id)
        .order_by(PurchaseOrder.order_date.desc())
    )
    if status:
        q = q.where(PurchaseOrder.status == status)

    result = await db.execute(q)
    pos = result.scalars().unique().all()

    # Get SKU details for all items
    all_sku_ids = set()
    for po in pos:
        for item in po.items:
            all_sku_ids.add(item.sku_id)

    sku_map = {}
    if all_sku_ids:
        sku_rows = await db.execute(
            select(SKU.id, SKU.sku_code, SKU.description).where(SKU.id.in_(all_sku_ids))
        )
        sku_map = {row.id: {"code": row.sku_code, "description": row.description} for row in sku_rows.all()}

    po_list = []
    for po in pos:
        items = []
        for item in po.items:
            sku_info = sku_map.get(item.sku_id, {"code": "UNKNOWN", "description": ""})
            items.append({
                "id": str(item.id),
                "skuId": str(item.sku_id),
                "skuCode": sku_info["code"],
                "skuDescription": sku_info["description"],
                "qtyOrdered": item.qty_ordered,
                "qtyReceived": item.qty_received,
                "unitCost": _dec(item.unit_cost),
                "taxCode": item.tax_code,
                "lineTotal": _dec(item.line_total),
                "fullyReceived": item.qty_received >= item.qty_ordered,
            })

        po_list.append({
            "id": str(po.id),
            "poNumber": po.po_number,
            "orderDate": po.order_date.isoformat(),
            "expectedDeliveryDate": po.expected_delivery_date.isoformat() if po.expected_delivery_date else None,
            "status": po.status.value,
            "subtotal": _dec(po.subtotal),
            "taxTotal": _dec(po.tax_total),
            "grandTotal": _dec(po.grand_total),
            "currency": po.currency,
            "notes": po.notes,
            "itemCount": len(items),
            "items": items,
            "createdAt": po.created_at.isoformat() if po.created_at else None,
        })

    # Aggregates
    total_spend = sum(po["grandTotal"] for po in po_list)

    return DataResponse(data={
        "totalPurchaseOrders": len(po_list),
        "totalSpend": round(total_spend, 2),
        "purchaseOrders": po_list,
    })


# ------------------------------------------------------------------ #
# 4. DOCUMENTS — scanned order copies                                  #
# ------------------------------------------------------------------ #

@router.get("/{supplier_id}/documents")
async def list_supplier_documents(
    supplier_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all uploaded documents for this supplier."""
    from app.models.ai_artifact import AIArtifact

    result = await db.execute(select(Supplier.id).where(Supplier.id == supplier_id))
    if not result.scalar_one_or_none():
        raise HTTPException(404, "Supplier not found")

    result = await db.execute(
        select(AIArtifact)
        .where(
            AIArtifact.artifact_type == "supplier_document",
            AIArtifact.payload["supplier_id"].astext == str(supplier_id),
        )
        .order_by(AIArtifact.created_at.desc())
    )
    docs = result.scalars().all()

    return DataResponse(data={
        "totalDocuments": len(docs),
        "documents": [
            {
                "id": str(d.id),
                "filename": d.payload.get("filename", ""),
                "documentType": d.payload.get("document_type", "order"),
                "description": d.payload.get("description", ""),
                "gcsUri": d.gcs_uri,
                "poNumber": d.payload.get("po_number"),
                "uploadedAt": d.created_at.isoformat() if d.created_at else None,
                "status": d.status,
                "ocrText": d.payload.get("ocr_text"),
            }
            for d in docs
        ],
    })


@router.post("/{supplier_id}/documents", status_code=201)
async def upload_supplier_document(
    supplier_id: UUID,
    file: UploadFile = File(...),
    document_type: str = Query("order", regex="^(order|invoice|catalog|receipt|other)$"),
    description: str = Query(""),
    po_number: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a scanned document (PDF/image) for this supplier. Stored in GCS, metadata in DB."""
    from app.models.ai_artifact import AIArtifact
    from app.services import gcs

    result = await db.execute(select(Supplier).where(Supplier.id == supplier_id))
    supplier = result.scalar_one_or_none()
    if not supplier:
        raise HTTPException(404, "Supplier not found")

    # Read file
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:  # 20MB limit
        raise HTTPException(413, "File too large (max 20MB)")

    # Determine content type
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else "bin"
    content_type_map = {
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
    }
    content_type = content_type_map.get(ext, "application/octet-stream")

    # Upload to GCS
    artifact_id = uuid_mod.uuid4().hex[:12]
    gcs_path = f"suppliers/{supplier.supplier_code}/documents/{artifact_id}.{ext}"
    try:
        gcs_uri = await gcs.upload_bytes(data, gcs_path, content_type)
    except Exception as exc:
        logger.error("GCS upload failed: %s", exc)
        # Store locally referenced even if GCS fails
        gcs_uri = f"pending://{gcs_path}"

    # Save metadata
    artifact = AIArtifact(
        artifact_type="supplier_document",
        status="completed",
        payload={
            "supplier_id": str(supplier_id),
            "supplier_code": supplier.supplier_code,
            "filename": file.filename or f"document.{ext}",
            "document_type": document_type,
            "description": description,
            "po_number": po_number,
            "content_type": content_type,
            "size_bytes": len(data),
            "uploaded_by": str(current_user.id),
        },
        gcs_uri=gcs_uri,
    )
    db.add(artifact)
    await db.flush()
    await db.refresh(artifact)

    return DataResponse(data={
        "id": str(artifact.id),
        "filename": file.filename,
        "documentType": document_type,
        "gcsUri": gcs_uri,
        "sizeBytes": len(data),
        "uploadedAt": artifact.created_at.isoformat() if artifact.created_at else None,
    })


# ------------------------------------------------------------------ #
# 5. ANALYTICS — AI-powered purchase & sell-through analysis           #
# ------------------------------------------------------------------ #

@router.get("/{supplier_id}/analytics")
async def supplier_analytics(
    supplier_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """AI-powered supplier analytics: spend trends, product performance, sell-through, recommendations."""
    from app.services.ai_gateway import invoke, AIRequest

    # Verify supplier
    result = await db.execute(select(Supplier).where(Supplier.id == supplier_id))
    supplier = result.scalar_one_or_none()
    if not supplier:
        raise HTTPException(404, "Supplier not found")

    # --- Gather raw data ---

    # Monthly spend trend
    from sqlalchemy import literal_column
    month_trunc = func.date_trunc(literal_column("'month'"), PurchaseOrder.order_date)
    monthly_spend = await db.execute(
        select(
            month_trunc.label("month"),
            func.count(PurchaseOrder.id).label("po_count"),
            func.sum(PurchaseOrder.grand_total).label("spend"),
        )
        .where(PurchaseOrder.supplier_id == supplier_id)
        .group_by(month_trunc)
        .order_by(month_trunc)
    )
    spend_trend = [
        {"month": row.month.strftime("%Y-%m") if row.month else "", "poCount": row.po_count, "spend": _dec(row.spend)}
        for row in monthly_spend.all()
    ]

    # Top products by purchase volume
    top_purchased = await db.execute(
        select(
            SKU.sku_code,
            SKU.description,
            func.sum(PurchaseOrderItem.qty_ordered).label("total_qty"),
            func.sum(PurchaseOrderItem.line_total).label("total_cost"),
        )
        .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .join(SKU, PurchaseOrderItem.sku_id == SKU.id)
        .where(PurchaseOrder.supplier_id == supplier_id)
        .group_by(SKU.id, SKU.sku_code, SKU.description)
        .order_by(func.sum(PurchaseOrderItem.line_total).desc())
        .limit(20)
    )
    top_products = [
        {"skuCode": row.sku_code, "description": row.description, "totalQtyPurchased": row.total_qty, "totalCostSGD": _dec(row.total_cost)}
        for row in top_purchased.all()
    ]

    # Sell-through for this supplier's products
    sell_through = await db.execute(
        select(
            SKU.sku_code,
            SKU.description,
            SKU.cost_price,
            func.sum(OrderItem.qty).label("qty_sold"),
            func.sum(OrderItem.line_total).label("revenue"),
            func.avg(OrderItem.unit_price).label("avg_price"),
        )
        .join(Order, OrderItem.order_id == Order.id)
        .join(SKU, OrderItem.sku_id == SKU.id)
        .join(SupplierProduct, SupplierProduct.sku_id == SKU.id)
        .where(
            SupplierProduct.supplier_id == supplier_id,
            Order.status == OrderStatus.completed,
        )
        .group_by(SKU.id, SKU.sku_code, SKU.description, SKU.cost_price)
        .order_by(func.sum(OrderItem.line_total).desc())
    )
    sell_data = []
    for row in sell_through.all():
        margin = None
        if row.cost_price and row.avg_price and float(row.avg_price) > 0:
            margin = round(((float(row.avg_price) - float(row.cost_price)) / float(row.avg_price)) * 100, 1)
        sell_data.append({
            "skuCode": row.sku_code,
            "description": row.description,
            "qtySold": row.qty_sold,
            "revenue": _dec(row.revenue),
            "avgSellingPrice": round(float(row.avg_price), 2) if row.avg_price else None,
            "costPrice": _dec(row.cost_price),
            "marginPercent": margin,
        })

    # Inventory status for this supplier's products
    inv_status = await db.execute(
        select(
            SKU.sku_code,
            SKU.description,
            SKU.is_unique_piece,
            Inventory.qty_on_hand,
            Inventory.reorder_level,
            Inventory.location_status,
        )
        .join(SupplierProduct, SupplierProduct.sku_id == SKU.id)
        .join(Inventory, Inventory.sku_id == SKU.id)
        .where(SupplierProduct.supplier_id == supplier_id)
        .order_by(Inventory.qty_on_hand)
    )
    inventory_items = []
    for row in inv_status.all():
        loc = row.location_status.value if hasattr(row.location_status, 'value') else str(row.location_status)
        inventory_items.append({
            "skuCode": row.sku_code,
            "description": row.description,
            "isUniquePiece": row.is_unique_piece,
            "qtyOnHand": row.qty_on_hand,
            "reorderLevel": row.reorder_level,
            "location": loc,
            "lowStock": row.qty_on_hand <= row.reorder_level,
        })

    # --- Build analytics summary ---
    total_spend = sum(s["spend"] for s in spend_trend)
    total_revenue = sum(s["revenue"] for s in sell_data)
    total_margin = total_revenue - total_spend if total_revenue > 0 else 0

    analytics = {
        "summary": {
            "totalSpendSGD": round(total_spend, 2),
            "totalRevenueSGD": round(total_revenue, 2),
            "grossMarginSGD": round(total_margin, 2),
            "marginPercent": round((total_margin / total_revenue * 100), 1) if total_revenue > 0 else None,
            "uniqueProductsPurchased": len(top_products),
            "productsSold": len(sell_data),
            "lowStockItems": sum(1 for i in inventory_items if i["lowStock"]),
        },
        "spendTrend": spend_trend,
        "topProducts": top_products,
        "sellThrough": sell_data,
        "inventory": inventory_items,
    }

    # --- AI Insights ---
    ai_context = json.dumps({
        "supplier": {"name": supplier.name, "country": supplier.country, "currency": supplier.currency},
        "totalSpend": round(total_spend, 2),
        "totalRevenue": round(total_revenue, 2),
        "productCount": len(top_products),
        "topProducts": top_products[:5],
        "sellThrough": sell_data[:5],
        "lowStockCount": analytics["summary"]["lowStockItems"],
        "spendTrend": spend_trend,
    }, default=str)

    prompt = f"""You are an AI purchasing advisor for a retail jewelry and decorative arts store at Changi Airport, Singapore.

Analyze this supplier data and provide actionable insights in JSON format:

{ai_context}

Return a JSON object with these keys:
- "supplierRating": string (Excellent/Good/Average/Poor) based on product performance and margin
- "keyInsights": array of 3-5 short insight strings about this supplier relationship
- "reorderRecommendations": array of objects with "skuCode", "reason", "urgency" (high/medium/low) for items that should be reordered
- "pricingInsights": array of 2-3 strings about pricing, margins, and opportunities
- "riskFactors": array of 1-3 strings about risks (stock-outs, concentration, currency exposure, etc.)
- "actionItems": array of 2-4 specific next steps the manager should take

Be specific, reference actual product codes and numbers. This is a real business — no generic advice."""

    try:
        ai_resp = await invoke(AIRequest(
            prompt=prompt,
            purpose="supplier_analytics",
            timeout_seconds=20,
            max_output_tokens=2048,
            response_mime_type="application/json",
            store_id=None,
        ))

        if not ai_resp.is_fallback:
            try:
                analytics["aiInsights"] = json.loads(ai_resp.text)
            except json.JSONDecodeError:
                analytics["aiInsights"] = {"raw": ai_resp.text}
        else:
            analytics["aiInsights"] = {"error": "AI temporarily unavailable", "fallback": True}

        analytics["aiMeta"] = {
            "model": ai_resp.model,
            "latencyMs": ai_resp.latency_ms,
            "costUSD": ai_resp.estimated_cost_usd,
        }
    except Exception as exc:
        logger.warning("AI analytics failed: %s", exc)
        analytics["aiInsights"] = {"error": str(exc), "fallback": True}
        analytics["aiMeta"] = None

    return DataResponse(data=analytics)
