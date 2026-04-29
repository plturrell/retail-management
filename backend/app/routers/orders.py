from __future__ import annotations

import uuid as uuid_mod
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from google.cloud.firestore_v1.client import Client as FirestoreClient

from app.firestore import get_firestore_db
from app.firestore_helpers import (
    create_document,
    get_document,
    query_collection,
    update_document,
)
from app.auth.dependencies import RoleEnum, get_current_user, require_store_access, require_store_role
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.inventory import InventoryType
from app.schemas.order import OrderCreate, OrderItemRead, OrderRead, OrderUpdate
from app.services.manager_copilot import adjustment_collection
from app.services.supply_chain import (
    SupplyActionSource,
    adjust_stage_inventory,
    ensure_finished_stage_inventory,
)
from app.services.tax import compute_line_tax

router = APIRouter(prefix="/api/stores/{store_id}/orders", tags=["orders"])


def _col(store_id: UUID) -> str:
    return f"stores/{store_id}/orders"


def _sku_col(store_id: UUID) -> str:
    return f"stores/{store_id}/inventory"


def _stock_col(store_id: UUID) -> str:
    return f"stores/{store_id}/stock"


def _generate_order_number() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid_mod.uuid4().hex[:6].upper()
    return f"ORD-{ts}-{short}"


def _actor_uuid(user: dict) -> UUID:
    return UUID(str(user.get("id")))


def _parse_order_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _to_read(data: dict) -> OrderRead:
    items = []
    for it in data.get("items", []):
        items.append(OrderItemRead(
            id=UUID(it["id"]) if isinstance(it.get("id"), str) else it.get("id", uuid_mod.uuid4()),
            order_id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
            sku_id=UUID(it["sku_id"]) if isinstance(it.get("sku_id"), str) else it.get("sku_id"),
            qty=it.get("qty", 0),
            unit_price=it.get("unit_price", 0),
            discount=it.get("discount", 0),
            line_total=it.get("line_total", 0),
            created_at=it.get("created_at", data.get("created_at", datetime.now(timezone.utc))),
        ))

    return OrderRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        order_number=data.get("order_number", ""),
        store_id=UUID(data["store_id"]) if isinstance(data.get("store_id"), str) else data.get("store_id"),
        staff_id=UUID(data["staff_id"]) if data.get("staff_id") else None,
        salesperson_id=UUID(data["salesperson_id"]) if data.get("salesperson_id") else None,
        order_date=data.get("order_date", datetime.now(timezone.utc)),
        subtotal=data.get("subtotal", 0),
        discount_total=data.get("discount_total", 0),
        tax_total=data.get("tax_total", 0),
        grand_total=data.get("grand_total", 0),
        payment_method=data.get("payment_method", ""),
        payment_ref=data.get("payment_ref"),
        status=data.get("status", "open"),
        source=data.get("source", "manual"),
        items=items,
        created_at=data.get("created_at", datetime.now(timezone.utc)),
        updated_at=data.get("updated_at"),
    )


@router.get("", response_model=PaginatedResponse[OrderRead])
async def list_orders(
    store_id: UUID,
    page: int = 1,
    page_size: int = 50,
    status: Optional[str] = None,
    source: Optional[str] = None,
    payment_method: Optional[str] = None,
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    _=Depends(require_store_access),
    db: FirestoreClient = Depends(get_firestore_db),
):
    all_items = query_collection(_col(store_id), order_by="-order_date")
    if status:
        all_items = [item for item in all_items if item.get("status") == status]
    if source:
        all_items = [item for item in all_items if item.get("source") == source]
    if payment_method:
        all_items = [item for item in all_items if item.get("payment_method") == payment_method]
    if date_from:
        from_dt = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
        all_items = [
            item for item in all_items
            if (parsed := _parse_order_datetime(item.get("order_date"))) is not None and parsed >= from_dt
        ]
    if date_to:
        to_dt = datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc)
        all_items = [
            item for item in all_items
            if (parsed := _parse_order_datetime(item.get("order_date"))) is not None and parsed <= to_dt
        ]

    total = len(all_items)
    offset = (page - 1) * page_size
    page_items = all_items[offset : offset + page_size]

    return PaginatedResponse(
        data=[_to_read(o) for o in page_items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{order_id}", response_model=DataResponse[OrderRead])
async def get_order(
    store_id: UUID,
    order_id: UUID,
    _=Depends(require_store_access),
    db: FirestoreClient = Depends(get_firestore_db),
):
    data = get_document(_col(store_id), str(order_id))
    if data is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return DataResponse(data=_to_read(data))


@router.post("", response_model=DataResponse[OrderRead], status_code=201)
async def create_order(
    store_id: UUID,
    payload: OrderCreate,
    _=Depends(require_store_role(RoleEnum.staff)),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    if payload.store_id != store_id:
        raise HTTPException(status_code=400, detail="Payload store_id must match route store_id")

    now = datetime.now(timezone.utc)
    sku_col = _sku_col(store_id)

    # ── 1. Build line items with tax ───
    subtotal = 0.0
    discount_total = 0.0
    tax_total = 0.0
    line_items: list[dict] = []

    for item in payload.items:
        sku = get_document(sku_col, str(item.sku_id))
        if sku is None:
            raise HTTPException(
                status_code=400,
                detail=f"SKU {item.sku_id} is not available in this store",
            )
        if sku.get("block_sales", False):
            raise HTTPException(
                status_code=400,
                detail=f"SKU {item.sku_id} is blocked for sales",
            )
        tax_code = sku.get("tax_code", "G")
        category_id = sku.get("category_id")

        # Auto-apply best promotion if no explicit discount was given
        promo_discount = item.discount
        if item.discount == 0:
            # Query promotions for this SKU or category
            from app.firestore_helpers import query_collection as qc
            promo_filters = [("sku_id", "==", str(item.sku_id))]
            promos = qc("promotions", filters=promo_filters)
            if category_id:
                cat_promos = qc("promotions", filters=[("category_id", "==", str(category_id))])
                promos.extend(cat_promos)

            if promos:
                from decimal import Decimal, ROUND_HALF_UP
                best = Decimal("0")
                price = Decimal(str(item.unit_price))
                for promo in promos:
                    method = promo.get("disc_method", "").upper()
                    value = Decimal(str(promo.get("disc_value", 0)))
                    if method == "PERCENT":
                        disc = (price * value / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    elif method == "AMOUNT":
                        disc = min(value, price)
                    elif method == "BOGO":
                        free_items = item.qty // 2
                        disc = (price * free_items / item.qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if item.qty > 0 else Decimal("0")
                    else:
                        disc = Decimal("0")
                    if disc > best:
                        best = disc
                promo_discount = float(best)

        line_total = round((item.unit_price - promo_discount) * item.qty, 2)
        if round(item.line_total, 2) != line_total:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid line_total for SKU {item.sku_id}",
            )
        line_tax = compute_line_tax(item.unit_price, item.qty, promo_discount, tax_code)

        subtotal += item.unit_price * item.qty
        discount_total += promo_discount * item.qty
        tax_total += line_tax

        item_id = str(uuid_mod.uuid4())
        line_items.append({
            "id": item_id,
            "sku_id": str(item.sku_id),
            "qty": item.qty,
            "unit_price": item.unit_price,
            "discount": promo_discount,
            "line_total": line_total,
            "created_at": now,
        })

    grand_total = round(subtotal - discount_total, 2)
    user_id = user.get("id", "")
    actor_user_id = _actor_uuid(user)

    requested_qty_by_sku: dict[str, int] = {}
    for line_item in line_items:
        requested_qty_by_sku[line_item["sku_id"]] = (
            requested_qty_by_sku.get(line_item["sku_id"], 0) + int(line_item["qty"])
        )

    for sku_id_raw, requested_qty in requested_qty_by_sku.items():
        sku_uuid = UUID(sku_id_raw)
        stage = ensure_finished_stage_inventory(
            store_id,
            sku_uuid,
            actor_user_id,
            source=SupplyActionSource.system,
        )
        available_qty = stage.quantity_on_hand if stage is not None else 0
        if available_qty < requested_qty:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient finished stock for SKU {sku_id_raw}: have {available_qty}, need {requested_qty}",
            )

    # ── 2. Create order document with embedded items ───
    order_id = str(uuid_mod.uuid4())
    order_data = {
        "order_number": _generate_order_number(),
        "store_id": str(store_id),
        "staff_id": str(payload.staff_id) if payload.staff_id else str(user_id),
        "salesperson_id": None,
        "order_date": payload.order_date or now,
        "subtotal": round(subtotal, 2),
        "discount_total": round(discount_total, 2),
        "tax_total": round(tax_total, 2),
        "grand_total": grand_total,
        "payment_method": payload.payment_method,
        "payment_ref": payload.payment_ref,
        "status": "open",
        "source": payload.source,
        "items": line_items,
        "created_at": now,
        "updated_at": now,
    }

    created = create_document(_col(store_id), order_data, doc_id=order_id)

    # ── 3. Deduct inventory from the finished-stage ledger ──
    for li in line_items:
        sku_uuid = UUID(li["sku_id"])
        stage = adjust_stage_inventory(
            store_id,
            sku_uuid,
            InventoryType.finished,
            actor_user_id,
            delta_qty=-li["qty"],
            source=SupplyActionSource.system,
            reference_type="order",
            reference_id=UUID(order_id),
        )
        stock_items = query_collection(
            _stock_col(store_id),
            filters=[("sku_id", "==", li["sku_id"])],
            limit=1,
        )
        adjustment_id = str(uuid_mod.uuid4())
        create_document(
            adjustment_collection(store_id),
            {
                "id": adjustment_id,
                "inventory_id": stock_items[0]["id"] if stock_items else None,
                "sku_id": li["sku_id"],
                "store_id": str(store_id),
                "quantity_delta": -li["qty"],
                "resulting_qty": stage.quantity_on_hand,
                "reason": f"Order {created['order_number']} completed",
                "source": "system",
                "created_by": str(user_id),
                "created_at": now,
                "note": f"Order line item {li['id']}",
            },
            doc_id=adjustment_id,
        )

    return DataResponse(data=_to_read(created))


@router.patch("/{order_id}", response_model=DataResponse[OrderRead])
async def update_order(
    store_id: UUID,
    order_id: UUID,
    payload: OrderUpdate,
    _=Depends(require_store_role(RoleEnum.staff)),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    col = _col(store_id)
    existing = get_document(col, str(order_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Order not found")

    updates = payload.model_dump(exclude_unset=True)
    if updates:
        updates["updated_at"] = datetime.now(timezone.utc)
        updated = update_document(col, str(order_id), updates)
    else:
        updated = existing
    return DataResponse(data=_to_read(updated))
