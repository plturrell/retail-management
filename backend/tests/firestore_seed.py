from __future__ import annotations

import uuid as uuid_mod
from datetime import datetime, timezone
from typing import Any

from app.firestore_helpers import create_document, query_collection, update_document
from app.schemas.inventory import InventoryType, SourcingStrategy


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def mirror_user(user: Any) -> dict[str, Any]:
    data = {
        "id": str(user.id),
        "firebase_uid": user.firebase_uid,
        "email": user.email,
        "full_name": user.full_name,
        "phone": getattr(user, "phone", None),
        "created_at": getattr(user, "created_at", None) or _now(),
        "updated_at": getattr(user, "updated_at", None) or _now(),
    }
    return create_document("users", data, doc_id=str(user.id))


def mirror_store(store: Any) -> dict[str, Any]:
    data = {
        "id": str(store.id),
        "store_code": getattr(store, "store_code", None),
        "name": store.name,
        "location": getattr(store, "location", None),
        "address": getattr(store, "address", None),
        "is_active": getattr(store, "is_active", True),
        "created_at": getattr(store, "created_at", None) or _now(),
        "updated_at": getattr(store, "updated_at", None) or _now(),
    }
    return create_document("stores", data, doc_id=str(store.id))


def mirror_role(role: Any) -> dict[str, Any]:
    data = {
        "id": str(role.id),
        "user_id": str(role.user_id),
        "store_id": str(role.store_id),
        "role": getattr(role.role, "value", role.role),
        "created_at": getattr(role, "created_at", None) or _now(),
    }
    return create_document(
        f"stores/{role.store_id}/roles",
        data,
        doc_id=str(role.user_id),
    )


def mirror_brand(brand: Any) -> dict[str, Any]:
    data = {
        "id": str(brand.id),
        "name": brand.name,
        "category_type": getattr(brand, "category_type", None),
        "created_at": getattr(brand, "created_at", None) or _now(),
    }
    return create_document("brands", data, doc_id=str(brand.id))


def mirror_category(category: Any) -> dict[str, Any]:
    data = {
        "id": str(category.id),
        "store_id": str(category.store_id),
        "parent_id": _to_str(getattr(category, "parent_id", None)),
        "catg_code": category.catg_code,
        "cag_catg_code": getattr(category, "cag_catg_code", None),
        "description": category.description,
        "created_at": getattr(category, "created_at", None) or _now(),
        "updated_at": getattr(category, "updated_at", None) or _now(),
    }
    return create_document(
        f"stores/{category.store_id}/categories",
        data,
        doc_id=str(category.id),
    )


def mirror_sku(sku: Any, *, qty_on_hand: int = 100) -> dict[str, Any]:
    created_at = getattr(sku, "created_at", None) or _now()
    updated_at = getattr(sku, "updated_at", None) or _now()
    data = {
        "id": str(sku.id),
        "sku_code": sku.sku_code,
        "description": sku.description,
        "store_id": str(sku.store_id),
        "category_id": _to_str(getattr(sku, "category_id", None)),
        "brand_id": _to_str(getattr(sku, "brand_id", None)),
        "tax_code": getattr(sku, "tax_code", "G"),
        "block_sales": bool(getattr(sku, "block_sales", False)),
        "cost_price": float(getattr(sku, "cost_price", 0) or 0),
        "supplier_name": getattr(sku, "supplier_name", None),
        "sourcing_strategy": getattr(
            getattr(sku, "sourcing_strategy", None),
            "value",
            getattr(sku, "sourcing_strategy", SourcingStrategy.supplier_premade.value),
        ),
        "created_at": created_at,
        "updated_at": updated_at,
    }
    create_document(
        f"stores/{sku.store_id}/inventory",
        data,
        doc_id=str(sku.id),
    )
    create_document("skus", data, doc_id=str(sku.id))

    stock_id = str(uuid_mod.uuid4())
    create_document(
        f"stores/{sku.store_id}/stock",
        {
            "id": stock_id,
            "sku_id": str(sku.id),
            "store_id": str(sku.store_id),
            "qty_on_hand": qty_on_hand,
            "reorder_level": 0,
            "reorder_qty": 0,
            "serial_number": None,
            "last_updated": updated_at,
            "created_at": created_at,
            "updated_at": updated_at,
        },
        doc_id=stock_id,
    )
    return data


def mirror_order(
    *,
    store_id: Any,
    order_number: str | None = None,
    salesperson_id: Any = None,
    staff_id: Any = None,
    order_date: Any = None,
    grand_total: float = 0.0,
    subtotal: float | None = None,
    discount_total: float = 0.0,
    tax_total: float = 0.0,
    payment_method: str = "cash",
    payment_ref: str | None = None,
    status: str = "completed",
    source: str = "manual",
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    now = _now()
    doc_id = str(uuid_mod.uuid4())
    data = {
        "id": doc_id,
        "order_number": order_number or f"ORD-{uuid_mod.uuid4().hex[:8].upper()}",
        "store_id": str(store_id),
        "staff_id": _to_str(staff_id),
        "salesperson_id": _to_str(salesperson_id),
        "order_date": order_date or now.isoformat(),
        "subtotal": float(subtotal if subtotal is not None else grand_total),
        "discount_total": float(discount_total),
        "tax_total": float(tax_total),
        "grand_total": float(grand_total),
        "payment_method": payment_method,
        "payment_ref": payment_ref,
        "status": status,
        "source": source,
        "items": items or [],
        "created_at": now,
        "updated_at": now,
    }
    return create_document(
        f"stores/{store_id}/orders",
        data,
        doc_id=doc_id,
    )


def update_salesperson_for_store_orders(store_id: Any, salesperson_id: Any) -> None:
    for order in query_collection(f"stores/{store_id}/orders"):
        update_document(
            f"stores/{store_id}/orders",
            str(order["id"]),
            {
                "salesperson_id": str(salesperson_id),
                "updated_at": _now(),
            },
        )


def ensure_finished_stage_inventory(store_id: Any, sku_id: Any, *, quantity_on_hand: int = 100) -> dict[str, Any]:
    doc_id = f"{InventoryType.finished.value}:{sku_id}"
    now = _now()
    data = {
        "id": str(uuid_mod.uuid4()),
        "ledger_key": doc_id,
        "store_id": str(store_id),
        "sku_id": str(sku_id),
        "inventory_type": InventoryType.finished.value,
        "quantity_on_hand": quantity_on_hand,
        "incoming_quantity": 0,
        "allocated_quantity": 0,
        "available_quantity": quantity_on_hand,
        "source": "test_seed",
        "created_at": now,
        "updated_at": now,
    }
    return create_document(
        f"stores/{store_id}/stage_inventory",
        data,
        doc_id=doc_id,
    )


def mirror_time_entry(entry: Any, *, user_name: str = "Unknown") -> dict[str, Any]:
    data = {
        "id": str(entry.id),
        "user_id": str(entry.user_id),
        "store_id": str(entry.store_id),
        "clock_in": entry.clock_in,
        "clock_out": entry.clock_out,
        "break_minutes": entry.break_minutes,
        "notes": getattr(entry, "notes", None),
        "status": getattr(getattr(entry, "status", None), "value", getattr(entry, "status", "pending")),
        "approved_by": _to_str(getattr(entry, "approved_by", None)),
        "user_name": user_name,
        "created_at": getattr(entry, "created_at", None) or _now(),
        "updated_at": getattr(entry, "updated_at", None) or _now(),
    }
    return create_document(
        f"stores/{entry.store_id}/timesheets",
        data,
        doc_id=str(entry.id),
    )
