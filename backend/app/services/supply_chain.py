from __future__ import annotations

import uuid as uuid_mod
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from app.firestore_helpers import create_document, get_document, query_collection, update_document
from app.schemas.inventory import InventoryType, SourcingStrategy
from app.schemas.supply_chain import (
    BOMComponentInput,
    BOMComponentRead,
    BOMRecipeCreate,
    BOMRecipeRead,
    ProductionEventRead,
    PurchaseOrderCreate,
    PurchaseOrderLineRead,
    PurchaseOrderRead,
    PurchaseOrderReceiveRequest,
    PurchaseOrderStatus,
    PurchaseReceiptRead,
    StageInventoryRead,
    StockTransferCreate,
    StockTransferRead,
    StockTransferReceiveRequest,
    SupplierCreate,
    SupplierRead,
    SupplierUpdate,
    SupplyActionSource,
    SupplyChainSummaryRead,
    TransferStatus,
    WorkOrderCompleteRequest,
    WorkOrderCreate,
    WorkOrderRead,
    WorkOrderStatus,
    WorkOrderType,
)


def sku_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/inventory"


def stock_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/stock"


def supplier_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/suppliers"


def stage_inventory_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/stage_inventory"


def purchase_order_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/purchase_orders"


def purchase_receipt_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/purchase_receipts"


def bom_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/bom_recipes"


def work_order_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/work_orders"


def production_event_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/production_events"


def transfer_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/stock_transfers"


def _parse_datetime(value: Any) -> datetime | None:
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


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _parse_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            return None
    return None


def _stage_doc_id(sku_id: UUID, inventory_type: InventoryType) -> str:
    return f"{inventory_type.value}:{sku_id}"


def _load_sku_map(store_id: UUID) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("id")): row
        for row in query_collection(sku_collection(store_id))
        if row and row.get("id")
    }


def _load_supplier_map(store_id: UUID) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("id")): row
        for row in query_collection(supplier_collection(store_id))
        if row and row.get("id")
    }


def _inventory_stage_for_purchase(sku: dict[str, Any]) -> InventoryType:
    sourcing_strategy = SourcingStrategy(
        sku.get("sourcing_strategy", SourcingStrategy.supplier_premade.value)
    )
    if sourcing_strategy == SourcingStrategy.supplier_premade:
        return InventoryType.purchased
    return InventoryType.material


def _stock_row_for_sku(store_id: UUID, sku_id: UUID) -> dict[str, Any] | None:
    rows = query_collection(
        stock_collection(store_id),
        filters=[("sku_id", "==", str(sku_id))],
        limit=1,
    )
    return rows[0] if rows else None


def _to_stage_read(data: dict[str, Any], sku_map: dict[str, dict[str, Any]]) -> StageInventoryRead:
    sku_id = str(data.get("sku_id", ""))
    sku = sku_map.get(sku_id, {})
    return StageInventoryRead(
        id=_parse_uuid(data.get("id")) or uuid_mod.uuid4(),
        store_id=_parse_uuid(data.get("store_id")) or uuid_mod.uuid4(),
        sku_id=_parse_uuid(sku_id) or uuid_mod.uuid4(),
        sku_code=sku.get("sku_code", ""),
        description=sku.get("description", ""),
        inventory_type=InventoryType(data.get("inventory_type", InventoryType.finished.value)),
        sourcing_strategy=SourcingStrategy(
            sku.get("sourcing_strategy", SourcingStrategy.supplier_premade.value)
        ),
        supplier_name=data.get("supplier_name") or sku.get("supplier_name"),
        quantity_on_hand=int(data.get("quantity_on_hand", 0) or 0),
        incoming_quantity=int(data.get("incoming_quantity", 0) or 0),
        allocated_quantity=int(data.get("allocated_quantity", 0) or 0),
        available_quantity=int(data.get("available_quantity", 0) or 0),
        unit_cost=float(data.get("unit_cost")) if data.get("unit_cost") is not None else None,
        last_reference_type=data.get("last_reference_type"),
        last_reference_id=_parse_uuid(data.get("last_reference_id")),
        source=SupplyActionSource(data.get("source", SupplyActionSource.manual.value)),
        created_at=_parse_datetime(data.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_parse_datetime(data.get("updated_at")),
        updated_by=_parse_uuid(data.get("updated_by")),
    )


def _to_supplier_read(data: dict[str, Any]) -> SupplierRead:
    return SupplierRead(
        id=_parse_uuid(data.get("id")) or uuid_mod.uuid4(),
        store_id=_parse_uuid(data.get("store_id")) or uuid_mod.uuid4(),
        name=data.get("name", ""),
        contact_name=data.get("contact_name"),
        email=data.get("email"),
        phone=data.get("phone"),
        lead_time_days=int(data.get("lead_time_days", 7) or 0),
        currency=data.get("currency", "SGD"),
        notes=data.get("notes"),
        is_active=bool(data.get("is_active", True)),
        created_by=_parse_uuid(data.get("created_by")),
        updated_by=_parse_uuid(data.get("updated_by")),
        created_at=_parse_datetime(data.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_parse_datetime(data.get("updated_at")),
    )


def _to_bom_component(data: dict[str, Any], sku_map: dict[str, dict[str, Any]]) -> BOMComponentRead:
    sku_id = str(data.get("sku_id", ""))
    sku = sku_map.get(sku_id, {})
    return BOMComponentRead(
        sku_id=_parse_uuid(sku_id) or uuid_mod.uuid4(),
        sku_code=sku.get("sku_code", ""),
        description=sku.get("description", ""),
        quantity_required=int(data.get("quantity_required", 0) or 0),
        note=data.get("note"),
    )


def _to_purchase_order_read(
    data: dict[str, Any],
    sku_map: dict[str, dict[str, Any]],
    supplier_map: dict[str, dict[str, Any]],
) -> PurchaseOrderRead:
    lines: list[PurchaseOrderLineRead] = []
    for raw_line in data.get("lines", []):
        sku_id = str(raw_line.get("sku_id", ""))
        sku = sku_map.get(sku_id, {})
        lines.append(
            PurchaseOrderLineRead(
                line_id=_parse_uuid(raw_line.get("line_id")) or uuid_mod.uuid4(),
                sku_id=_parse_uuid(sku_id) or uuid_mod.uuid4(),
                sku_code=sku.get("sku_code", ""),
                description=sku.get("description", ""),
                stage_inventory_type=InventoryType(
                    raw_line.get("stage_inventory_type", InventoryType.purchased.value)
                ),
                quantity=int(raw_line.get("quantity", 0) or 0),
                unit_cost=float(raw_line.get("unit_cost", 0) or 0),
                received_quantity=int(raw_line.get("received_quantity", 0) or 0),
                open_quantity=int(raw_line.get("open_quantity", 0) or 0),
                note=raw_line.get("note"),
            )
        )
    supplier = supplier_map.get(str(data.get("supplier_id")), {})
    return PurchaseOrderRead(
        id=_parse_uuid(data.get("id")) or uuid_mod.uuid4(),
        store_id=_parse_uuid(data.get("store_id")) or uuid_mod.uuid4(),
        supplier_id=_parse_uuid(data.get("supplier_id")) or uuid_mod.uuid4(),
        supplier_name=data.get("supplier_name") or supplier.get("name"),
        status=PurchaseOrderStatus(data.get("status", PurchaseOrderStatus.ordered.value)),
        lines=lines,
        total_quantity=int(data.get("total_quantity", 0) or 0),
        total_cost=float(data.get("total_cost", 0) or 0),
        ordered_at=_parse_date(data.get("ordered_at")),
        expected_delivery_date=_parse_date(data.get("expected_delivery_date")),
        last_received_at=_parse_datetime(data.get("last_received_at")),
        note=data.get("note"),
        source=SupplyActionSource(data.get("source", SupplyActionSource.manual.value)),
        recommendation_id=_parse_uuid(data.get("recommendation_id")),
        created_by=_parse_uuid(data.get("created_by")),
        updated_by=_parse_uuid(data.get("updated_by")),
        created_at=_parse_datetime(data.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_parse_datetime(data.get("updated_at")),
    )


def _to_receipt_read(data: dict[str, Any]) -> PurchaseReceiptRead:
    return PurchaseReceiptRead(
        id=_parse_uuid(data.get("id")) or uuid_mod.uuid4(),
        purchase_order_id=_parse_uuid(data.get("purchase_order_id")) or uuid_mod.uuid4(),
        store_id=_parse_uuid(data.get("store_id")) or uuid_mod.uuid4(),
        note=data.get("note"),
        received_at=_parse_datetime(data.get("received_at")) or datetime.now(timezone.utc),
        received_by=_parse_uuid(data.get("received_by")),
        lines=data.get("lines", []),
    )


def _to_bom_read(data: dict[str, Any], sku_map: dict[str, dict[str, Any]]) -> BOMRecipeRead:
    finished_sku = sku_map.get(str(data.get("finished_sku_id")), {})
    components = [_to_bom_component(item, sku_map) for item in data.get("components", [])]
    return BOMRecipeRead(
        id=_parse_uuid(data.get("id")) or uuid_mod.uuid4(),
        store_id=_parse_uuid(data.get("store_id")) or uuid_mod.uuid4(),
        finished_sku_id=_parse_uuid(data.get("finished_sku_id")) or uuid_mod.uuid4(),
        finished_sku_code=finished_sku.get("sku_code", ""),
        finished_description=finished_sku.get("description", ""),
        name=data.get("name", ""),
        yield_quantity=int(data.get("yield_quantity", 1) or 1),
        components=components,
        notes=data.get("notes"),
        created_by=_parse_uuid(data.get("created_by")),
        updated_by=_parse_uuid(data.get("updated_by")),
        created_at=_parse_datetime(data.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_parse_datetime(data.get("updated_at")),
    )


def _to_work_order_read(data: dict[str, Any], sku_map: dict[str, dict[str, Any]]) -> WorkOrderRead:
    finished_sku = sku_map.get(str(data.get("finished_sku_id")), {})
    components = [_to_bom_component(item, sku_map) for item in data.get("components", [])]
    return WorkOrderRead(
        id=_parse_uuid(data.get("id")) or uuid_mod.uuid4(),
        store_id=_parse_uuid(data.get("store_id")) or uuid_mod.uuid4(),
        finished_sku_id=_parse_uuid(data.get("finished_sku_id")) or uuid_mod.uuid4(),
        finished_sku_code=finished_sku.get("sku_code", ""),
        finished_description=finished_sku.get("description", ""),
        work_order_type=WorkOrderType(data.get("work_order_type", WorkOrderType.standard.value)),
        status=WorkOrderStatus(data.get("status", WorkOrderStatus.scheduled.value)),
        target_quantity=int(data.get("target_quantity", 0) or 0),
        completed_quantity=int(data.get("completed_quantity", 0) or 0),
        bom_id=_parse_uuid(data.get("bom_id")),
        components=components,
        due_date=_parse_date(data.get("due_date")),
        note=data.get("note"),
        source=SupplyActionSource(data.get("source", SupplyActionSource.manual.value)),
        recommendation_id=_parse_uuid(data.get("recommendation_id")),
        created_by=_parse_uuid(data.get("created_by")),
        updated_by=_parse_uuid(data.get("updated_by")),
        created_at=_parse_datetime(data.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_parse_datetime(data.get("updated_at")),
    )


def _to_production_event_read(data: dict[str, Any]) -> ProductionEventRead:
    return ProductionEventRead(
        id=_parse_uuid(data.get("id")) or uuid_mod.uuid4(),
        store_id=_parse_uuid(data.get("store_id")) or uuid_mod.uuid4(),
        work_order_id=_parse_uuid(data.get("work_order_id")) or uuid_mod.uuid4(),
        event_type=data.get("event_type", "unknown"),
        output_quantity=int(data.get("output_quantity", 0) or 0),
        note=data.get("note"),
        created_by=_parse_uuid(data.get("created_by")),
        created_at=_parse_datetime(data.get("created_at")) or datetime.now(timezone.utc),
        consumed_components=[
            BOMComponentInput(
                sku_id=_parse_uuid(item.get("sku_id")) or uuid_mod.uuid4(),
                quantity_required=int(item.get("quantity_required", 0) or 0),
                note=item.get("note"),
            )
            for item in data.get("consumed_components", [])
        ],
    )


def _to_transfer_read(data: dict[str, Any], sku_map: dict[str, dict[str, Any]]) -> StockTransferRead:
    sku = sku_map.get(str(data.get("sku_id")), {})
    return StockTransferRead(
        id=_parse_uuid(data.get("id")) or uuid_mod.uuid4(),
        store_id=_parse_uuid(data.get("store_id")) or uuid_mod.uuid4(),
        sku_id=_parse_uuid(data.get("sku_id")) or uuid_mod.uuid4(),
        sku_code=sku.get("sku_code", ""),
        description=sku.get("description", ""),
        quantity=int(data.get("quantity", 0) or 0),
        from_inventory_type=InventoryType(
            data.get("from_inventory_type", InventoryType.purchased.value)
        ),
        to_inventory_type=InventoryType(data.get("to_inventory_type", InventoryType.finished.value)),
        status=TransferStatus(data.get("status", TransferStatus.in_transit.value)),
        note=data.get("note"),
        source=SupplyActionSource(data.get("source", SupplyActionSource.manual.value)),
        recommendation_id=_parse_uuid(data.get("recommendation_id")),
        dispatched_at=_parse_datetime(data.get("dispatched_at")),
        received_at=_parse_datetime(data.get("received_at")),
        created_by=_parse_uuid(data.get("created_by")),
        updated_by=_parse_uuid(data.get("updated_by")),
        received_by=_parse_uuid(data.get("received_by")),
        created_at=_parse_datetime(data.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_parse_datetime(data.get("updated_at")),
    )


def _sync_finished_stock(
    store_id: UUID,
    sku_id: UUID,
    quantity_on_hand: int,
    actor_user_id: UUID,
    *,
    source: SupplyActionSource,
) -> dict[str, Any]:
    if quantity_on_hand < 0:
        raise ValueError("Finished inventory mirror cannot become negative")
    now = datetime.now(timezone.utc)
    existing = _stock_row_for_sku(store_id, sku_id)
    if existing:
        return update_document(
            stock_collection(store_id),
            str(existing.get("id")),
            {
                "qty_on_hand": quantity_on_hand,
                "last_updated": now,
                "source": source.value,
                "updated_by": str(actor_user_id),
                "updated_at": now,
            },
        )

    stock_id = str(uuid_mod.uuid4())
    return create_document(
        stock_collection(store_id),
        {
            "id": stock_id,
            "sku_id": str(sku_id),
            "store_id": str(store_id),
            "qty_on_hand": quantity_on_hand,
            "reorder_level": 0,
            "reorder_qty": 0,
            "serial_number": None,
            "last_updated": now,
            "source": source.value,
            "created_by": str(actor_user_id),
            "updated_by": str(actor_user_id),
            "created_at": now,
            "updated_at": now,
        },
        doc_id=stock_id,
    )


def ensure_finished_stage_inventory(
    store_id: UUID,
    sku_id: UUID,
    actor_user_id: UUID,
    *,
    source: SupplyActionSource = SupplyActionSource.system,
) -> StageInventoryRead | None:
    doc_id = _stage_doc_id(sku_id, InventoryType.finished)
    existing = get_document(stage_inventory_collection(store_id), doc_id)
    sku_map = _load_sku_map(store_id)
    if existing is not None:
        return _to_stage_read(existing, sku_map)

    stock_row = _stock_row_for_sku(store_id, sku_id)
    if stock_row is None:
        return None

    sku = sku_map.get(str(sku_id))
    if not sku:
        raise ValueError("SKU not found")

    now = datetime.now(timezone.utc)
    quantity_on_hand = int(stock_row.get("qty_on_hand", 0) or 0)
    created = create_document(
        stage_inventory_collection(store_id),
        {
            "id": str(uuid_mod.uuid4()),
            "ledger_key": doc_id,
            "store_id": str(store_id),
            "sku_id": str(sku_id),
            "inventory_type": InventoryType.finished.value,
            "quantity_on_hand": quantity_on_hand,
            "incoming_quantity": 0,
            "allocated_quantity": 0,
            "available_quantity": quantity_on_hand,
            "unit_cost": sku.get("cost_price"),
            "supplier_name": sku.get("supplier_name"),
            "sourcing_strategy": sku.get(
                "sourcing_strategy",
                SourcingStrategy.supplier_premade.value,
            ),
            "last_reference_type": "legacy_stock_bootstrap",
            "last_reference_id": str(stock_row.get("id")) if stock_row.get("id") else None,
            "source": source.value,
            "created_at": _parse_datetime(stock_row.get("created_at")) or now,
            "updated_at": now,
            "updated_by": str(actor_user_id),
        },
        doc_id=doc_id,
    )
    _sync_finished_stock(
        store_id,
        sku_id,
        quantity_on_hand,
        actor_user_id,
        source=source,
    )
    return _to_stage_read(created, sku_map)


def adjust_stage_inventory(
    store_id: UUID,
    sku_id: UUID,
    inventory_type: InventoryType,
    actor_user_id: UUID,
    *,
    delta_qty: int = 0,
    delta_incoming: int = 0,
    delta_allocated: int = 0,
    unit_cost: float | None = None,
    supplier_name: str | None = None,
    sourcing_strategy: SourcingStrategy | None = None,
    source: SupplyActionSource = SupplyActionSource.manual,
    reference_type: str | None = None,
    reference_id: UUID | None = None,
) -> StageInventoryRead:
    sku_map = _load_sku_map(store_id)
    sku = sku_map.get(str(sku_id))
    if not sku:
        raise ValueError("SKU not found")

    doc_id = _stage_doc_id(sku_id, inventory_type)
    existing = get_document(stage_inventory_collection(store_id), doc_id)
    now = datetime.now(timezone.utc)

    if existing is None:
        existing = {
            "id": str(uuid_mod.uuid4()),
            "ledger_key": doc_id,
            "store_id": str(store_id),
            "sku_id": str(sku_id),
            "inventory_type": inventory_type.value,
            "quantity_on_hand": 0,
            "incoming_quantity": 0,
            "allocated_quantity": 0,
            "available_quantity": 0,
            "unit_cost": unit_cost,
            "supplier_name": supplier_name or sku.get("supplier_name"),
            "sourcing_strategy": (sourcing_strategy or SourcingStrategy(
                sku.get("sourcing_strategy", SourcingStrategy.supplier_premade.value)
            )).value,
            "source": source.value,
            "created_at": now,
            "updated_at": now,
            "updated_by": str(actor_user_id),
        }
        create_document(stage_inventory_collection(store_id), existing, doc_id=doc_id)

    quantity_on_hand = int(existing.get("quantity_on_hand", 0) or 0) + delta_qty
    incoming_quantity = int(existing.get("incoming_quantity", 0) or 0) + delta_incoming
    allocated_quantity = int(existing.get("allocated_quantity", 0) or 0) + delta_allocated

    if quantity_on_hand < 0:
        raise ValueError(f"{inventory_type.value.title()} ledger would become negative for this SKU")
    if incoming_quantity < 0:
        raise ValueError("Incoming quantity cannot be negative")
    if allocated_quantity < 0:
        raise ValueError("Allocated quantity cannot be negative")

    available_quantity = quantity_on_hand - allocated_quantity
    if available_quantity < 0:
        raise ValueError("Allocated quantity exceeds quantity on hand")

    updates = {
        "quantity_on_hand": quantity_on_hand,
        "incoming_quantity": incoming_quantity,
        "allocated_quantity": allocated_quantity,
        "available_quantity": available_quantity,
        "unit_cost": unit_cost if unit_cost is not None else existing.get("unit_cost"),
        "supplier_name": supplier_name or existing.get("supplier_name") or sku.get("supplier_name"),
        "sourcing_strategy": (
            sourcing_strategy.value
            if sourcing_strategy is not None
            else existing.get("sourcing_strategy")
            or sku.get("sourcing_strategy", SourcingStrategy.supplier_premade.value)
        ),
        "last_reference_type": reference_type,
        "last_reference_id": str(reference_id) if reference_id else None,
        "source": source.value,
        "updated_at": now,
        "updated_by": str(actor_user_id),
    }
    updated = update_document(stage_inventory_collection(store_id), doc_id, updates)

    if inventory_type == InventoryType.finished:
        _sync_finished_stock(
            store_id,
            sku_id,
            quantity_on_hand,
            actor_user_id,
            source=source,
        )

    return _to_stage_read(updated, sku_map)


def list_stage_inventory(
    store_id: UUID,
    *,
    inventory_type: InventoryType | None = None,
    sku_id: UUID | None = None,
) -> list[StageInventoryRead]:
    docs = query_collection(stage_inventory_collection(store_id), order_by="inventory_type")
    sku_map = _load_sku_map(store_id)
    rows = [_to_stage_read(doc, sku_map) for doc in docs]
    if inventory_type is not None:
        rows = [row for row in rows if row.inventory_type == inventory_type]
    if sku_id is not None:
        rows = [row for row in rows if row.sku_id == sku_id]
    rows.sort(key=lambda item: (item.inventory_type.value, item.sku_code))
    return rows


def supply_chain_summary(store_id: UUID) -> SupplyChainSummaryRead:
    positions = list_stage_inventory(store_id)
    purchase_orders = list_purchase_orders(store_id)
    work_orders = list_work_orders(store_id)
    transfers = list_stock_transfers(store_id)
    return SupplyChainSummaryRead(
        store_id=store_id,
        supplier_count=len(list_suppliers(store_id)),
        open_purchase_orders=sum(
            1
            for item in purchase_orders
            if item.status in {PurchaseOrderStatus.ordered, PurchaseOrderStatus.partially_received}
        ),
        active_work_orders=sum(
            1
            for item in work_orders
            if item.status in {WorkOrderStatus.scheduled, WorkOrderStatus.in_progress}
        ),
        in_transit_transfers=sum(1 for item in transfers if item.status == TransferStatus.in_transit),
        purchased_units=sum(item.quantity_on_hand for item in positions if item.inventory_type == InventoryType.purchased),
        material_units=sum(item.quantity_on_hand for item in positions if item.inventory_type == InventoryType.material),
        finished_units=sum(item.quantity_on_hand for item in positions if item.inventory_type == InventoryType.finished),
        open_recommendation_linked_orders=sum(
            1
            for item in purchase_orders + work_orders + transfers
            if item.recommendation_id is not None
            and getattr(item, "status", None)
            not in {PurchaseOrderStatus.received, WorkOrderStatus.completed, TransferStatus.received}
        ),
    )


def list_suppliers(store_id: UUID, *, active_only: bool = False) -> list[SupplierRead]:
    docs = query_collection(supplier_collection(store_id), order_by="name")
    rows = [_to_supplier_read(doc) for doc in docs]
    if active_only:
        rows = [row for row in rows if row.is_active]
    return rows


def create_supplier(store_id: UUID, payload: SupplierCreate, actor_user_id: UUID) -> SupplierRead:
    now = datetime.now(timezone.utc)
    doc_id = str(uuid_mod.uuid4())
    doc = payload.model_dump()
    doc.update(
        {
            "id": doc_id,
            "store_id": str(store_id),
            "created_by": str(actor_user_id),
            "updated_by": str(actor_user_id),
            "created_at": now,
            "updated_at": now,
        }
    )
    created = create_document(supplier_collection(store_id), doc, doc_id=doc_id)
    return _to_supplier_read(created)


def update_supplier(store_id: UUID, supplier_id: UUID, payload: SupplierUpdate, actor_user_id: UUID) -> SupplierRead:
    existing = get_document(supplier_collection(store_id), str(supplier_id))
    if existing is None:
        raise ValueError("Supplier not found")
    updates = payload.model_dump(exclude_unset=True)
    updates["updated_by"] = str(actor_user_id)
    updates["updated_at"] = datetime.now(timezone.utc)
    updated = update_document(supplier_collection(store_id), str(supplier_id), updates)
    return _to_supplier_read(updated)


def list_purchase_orders(
    store_id: UUID,
    *,
    status: PurchaseOrderStatus | None = None,
) -> list[PurchaseOrderRead]:
    docs = query_collection(purchase_order_collection(store_id), order_by="-created_at")
    sku_map = _load_sku_map(store_id)
    supplier_map = _load_supplier_map(store_id)
    rows = [_to_purchase_order_read(doc, sku_map, supplier_map) for doc in docs]
    if status is not None:
        rows = [row for row in rows if row.status == status]
    return rows


def create_purchase_order(store_id: UUID, payload: PurchaseOrderCreate, actor_user_id: UUID) -> PurchaseOrderRead:
    supplier = get_document(supplier_collection(store_id), str(payload.supplier_id))
    if supplier is None:
        raise ValueError("Supplier not found")
    sku_map = _load_sku_map(store_id)
    now = datetime.now(timezone.utc)
    po_id = str(uuid_mod.uuid4())
    total_qty = 0
    total_cost = 0.0
    lines: list[dict[str, Any]] = []

    for line in payload.lines:
        sku = sku_map.get(str(line.sku_id))
        if not sku:
            raise ValueError("One of the purchase order SKUs does not exist")
        line_id = str(uuid_mod.uuid4())
        stage_type = _inventory_stage_for_purchase(sku)
        lines.append(
            {
                "line_id": line_id,
                "sku_id": str(line.sku_id),
                "quantity": line.quantity,
                "unit_cost": line.unit_cost,
                "received_quantity": 0,
                "open_quantity": line.quantity,
                "note": line.note,
                "stage_inventory_type": stage_type.value,
            }
        )
        total_qty += line.quantity
        total_cost += line.quantity * line.unit_cost
        adjust_stage_inventory(
            store_id,
            line.sku_id,
            stage_type,
            actor_user_id,
            delta_incoming=line.quantity,
            unit_cost=line.unit_cost,
            supplier_name=supplier.get("name"),
            sourcing_strategy=SourcingStrategy(
                sku.get("sourcing_strategy", SourcingStrategy.supplier_premade.value)
            ),
            source=payload.source,
            reference_type="purchase_order",
            reference_id=UUID(po_id),
        )

    doc = {
        "id": po_id,
        "store_id": str(store_id),
        "supplier_id": str(payload.supplier_id),
        "supplier_name": supplier.get("name"),
        "status": PurchaseOrderStatus.ordered.value,
        "lines": lines,
        "total_quantity": total_qty,
        "total_cost": round(total_cost, 2),
        "ordered_at": (payload.ordered_at or date.today()).isoformat(),
        "expected_delivery_date": payload.expected_delivery_date.isoformat() if payload.expected_delivery_date else None,
        "last_received_at": None,
        "note": payload.note,
        "source": payload.source.value,
        "recommendation_id": str(payload.recommendation_id) if payload.recommendation_id else None,
        "created_by": str(actor_user_id),
        "updated_by": str(actor_user_id),
        "created_at": now,
        "updated_at": now,
    }
    created = create_document(purchase_order_collection(store_id), doc, doc_id=po_id)
    return _to_purchase_order_read(created, sku_map, _load_supplier_map(store_id))


def receive_purchase_order(
    store_id: UUID,
    purchase_order_id: UUID,
    payload: PurchaseOrderReceiveRequest,
    actor_user_id: UUID,
) -> tuple[PurchaseOrderRead, PurchaseReceiptRead]:
    existing = get_document(purchase_order_collection(store_id), str(purchase_order_id))
    if existing is None:
        raise ValueError("Purchase order not found")
    if existing.get("status") in {PurchaseOrderStatus.received.value, PurchaseOrderStatus.cancelled.value}:
        raise ValueError("This purchase order can no longer receive stock")

    line_map = {str(line.get("line_id")): dict(line) for line in existing.get("lines", [])}
    sku_map = _load_sku_map(store_id)
    supplier_map = _load_supplier_map(store_id)

    for item in payload.lines:
        current_line = line_map.get(str(item.line_id))
        if current_line is None:
            raise ValueError("Receipt line does not match this purchase order")
        open_quantity = int(current_line.get("open_quantity", 0) or 0)
        if item.quantity_received > open_quantity:
            raise ValueError("Receipt quantity exceeds the open quantity on the purchase order")
        current_line["received_quantity"] = int(current_line.get("received_quantity", 0) or 0) + item.quantity_received
        current_line["open_quantity"] = open_quantity - item.quantity_received
        adjust_stage_inventory(
            store_id,
            _parse_uuid(current_line.get("sku_id")) or uuid_mod.uuid4(),
            InventoryType(current_line.get("stage_inventory_type", InventoryType.purchased.value)),
            actor_user_id,
            delta_qty=item.quantity_received,
            delta_incoming=-item.quantity_received,
            unit_cost=float(current_line.get("unit_cost", 0) or 0),
            source=SupplyActionSource.system,
            reference_type="purchase_receipt",
            reference_id=UUID(str(purchase_order_id)),
        )

    updated_lines = list(line_map.values())
    open_lines = [line for line in updated_lines if int(line.get("open_quantity", 0) or 0) > 0]
    status = (
        PurchaseOrderStatus.received.value
        if not open_lines
        else PurchaseOrderStatus.partially_received.value
    )
    now = datetime.now(timezone.utc)
    updated_doc = update_document(
        purchase_order_collection(store_id),
        str(purchase_order_id),
        {
            "lines": updated_lines,
            "status": status,
            "last_received_at": now,
            "updated_by": str(actor_user_id),
            "updated_at": now,
        },
    )

    receipt_id = str(uuid_mod.uuid4())
    receipt_doc = {
        "id": receipt_id,
        "purchase_order_id": str(purchase_order_id),
        "store_id": str(store_id),
        "note": payload.note,
        "received_at": datetime.combine(
            payload.received_at or date.today(),
            now.timetz(),
        ).isoformat(),
        "received_by": str(actor_user_id),
        "lines": [item.model_dump(mode="json") for item in payload.lines],
    }
    created_receipt = create_document(
        purchase_receipt_collection(store_id),
        receipt_doc,
        doc_id=receipt_id,
    )
    return (
        _to_purchase_order_read(updated_doc, sku_map, supplier_map),
        _to_receipt_read(created_receipt),
    )


def list_bom_recipes(store_id: UUID) -> list[BOMRecipeRead]:
    sku_map = _load_sku_map(store_id)
    docs = query_collection(bom_collection(store_id), order_by="name")
    return [_to_bom_read(doc, sku_map) for doc in docs]


def create_bom_recipe(store_id: UUID, payload: BOMRecipeCreate, actor_user_id: UUID) -> BOMRecipeRead:
    sku_map = _load_sku_map(store_id)
    if str(payload.finished_sku_id) not in sku_map:
        raise ValueError("Finished SKU not found")
    for component in payload.components:
        if str(component.sku_id) not in sku_map:
            raise ValueError("One of the BOM components does not exist")
    now = datetime.now(timezone.utc)
    bom_id = str(uuid_mod.uuid4())
    doc = {
        "id": bom_id,
        "store_id": str(store_id),
        "finished_sku_id": str(payload.finished_sku_id),
        "name": payload.name,
        "yield_quantity": payload.yield_quantity,
        "components": [component.model_dump(mode="json") for component in payload.components],
        "notes": payload.notes,
        "created_by": str(actor_user_id),
        "updated_by": str(actor_user_id),
        "created_at": now,
        "updated_at": now,
    }
    created = create_document(bom_collection(store_id), doc, doc_id=bom_id)
    return _to_bom_read(created, sku_map)


def list_work_orders(
    store_id: UUID,
    *,
    status: WorkOrderStatus | None = None,
) -> list[WorkOrderRead]:
    sku_map = _load_sku_map(store_id)
    docs = query_collection(work_order_collection(store_id), order_by="-created_at")
    rows = [_to_work_order_read(doc, sku_map) for doc in docs]
    if status is not None:
        rows = [row for row in rows if row.status == status]
    return rows


def create_work_order(store_id: UUID, payload: WorkOrderCreate, actor_user_id: UUID) -> WorkOrderRead:
    sku_map = _load_sku_map(store_id)
    finished_sku = sku_map.get(str(payload.finished_sku_id))
    if not finished_sku:
        raise ValueError("Finished SKU not found")

    yield_quantity = 1
    if payload.bom_id:
        bom = get_document(bom_collection(store_id), str(payload.bom_id))
        if bom is None:
            raise ValueError("BOM recipe not found")
        raw_components = bom.get("components", [])
        yield_quantity = int(bom.get("yield_quantity", 1) or 1)
    else:
        raw_components = [component.model_dump(mode="json") for component in payload.custom_components]
        if not raw_components and payload.work_order_type != WorkOrderType.custom:
            raise ValueError("A work order needs either a BOM recipe or custom components")

    work_order_id = str(uuid_mod.uuid4())
    components: list[dict[str, Any]] = []
    for item in raw_components:
        sku_id = _parse_uuid(item.get("sku_id"))
        if sku_id is None or str(sku_id) not in sku_map:
            raise ValueError("One of the work order components does not exist")
        quantity_required = int(item.get("quantity_required", 0) or 0)
        if quantity_required <= 0:
            raise ValueError("Work order component quantities must be positive")
        total_required = max(
            (quantity_required * payload.target_quantity + max(yield_quantity, 1) - 1)
            // max(yield_quantity, 1),
            1,
        )
        components.append(
            {
                "sku_id": str(sku_id),
                "quantity_required": total_required,
                "note": item.get("note"),
            }
        )
        adjust_stage_inventory(
            store_id,
            sku_id,
            InventoryType.material,
            actor_user_id,
            delta_allocated=total_required,
            source=payload.source,
            reference_type="work_order",
            reference_id=UUID(work_order_id),
        )

    now = datetime.now(timezone.utc)
    doc = {
        "id": work_order_id,
        "store_id": str(store_id),
        "finished_sku_id": str(payload.finished_sku_id),
        "work_order_type": payload.work_order_type.value,
        "status": WorkOrderStatus.scheduled.value,
        "target_quantity": payload.target_quantity,
        "completed_quantity": 0,
        "bom_id": str(payload.bom_id) if payload.bom_id else None,
        "components": components,
        "due_date": payload.due_date.isoformat() if payload.due_date else None,
        "note": payload.note,
        "source": payload.source.value,
        "recommendation_id": str(payload.recommendation_id) if payload.recommendation_id else None,
        "created_by": str(actor_user_id),
        "updated_by": str(actor_user_id),
        "created_at": now,
        "updated_at": now,
    }
    created = create_document(work_order_collection(store_id), doc, doc_id=work_order_id)
    create_document(
        production_event_collection(store_id),
        {
            "id": str(uuid_mod.uuid4()),
            "store_id": str(store_id),
            "work_order_id": work_order_id,
            "event_type": "scheduled",
            "output_quantity": 0,
            "note": payload.note,
            "created_by": str(actor_user_id),
            "created_at": now,
            "consumed_components": [],
        },
    )
    return _to_work_order_read(created, sku_map)


def start_work_order(store_id: UUID, work_order_id: UUID, actor_user_id: UUID) -> WorkOrderRead:
    existing = get_document(work_order_collection(store_id), str(work_order_id))
    if existing is None:
        raise ValueError("Work order not found")
    if existing.get("status") in {WorkOrderStatus.completed.value, WorkOrderStatus.cancelled.value}:
        raise ValueError("Work order cannot be started")
    now = datetime.now(timezone.utc)
    updated = update_document(
        work_order_collection(store_id),
        str(work_order_id),
        {
            "status": WorkOrderStatus.in_progress.value,
            "updated_by": str(actor_user_id),
            "updated_at": now,
        },
    )
    create_document(
        production_event_collection(store_id),
        {
            "id": str(uuid_mod.uuid4()),
            "store_id": str(store_id),
            "work_order_id": str(work_order_id),
            "event_type": "started",
            "output_quantity": 0,
            "note": "Work order started",
            "created_by": str(actor_user_id),
            "created_at": now,
            "consumed_components": [],
        },
    )
    return _to_work_order_read(updated, _load_sku_map(store_id))


def complete_work_order(
    store_id: UUID,
    work_order_id: UUID,
    payload: WorkOrderCompleteRequest,
    actor_user_id: UUID,
) -> tuple[WorkOrderRead, ProductionEventRead]:
    existing = get_document(work_order_collection(store_id), str(work_order_id))
    if existing is None:
        raise ValueError("Work order not found")
    if existing.get("status") == WorkOrderStatus.completed.value:
        raise ValueError("Work order is already complete")

    target_quantity = int(existing.get("target_quantity", 0) or 0)
    completed_quantity = int(existing.get("completed_quantity", 0) or 0)
    remaining_quantity = target_quantity - completed_quantity
    output_quantity = payload.completed_quantity or remaining_quantity
    if output_quantity <= 0 or output_quantity > remaining_quantity:
        raise ValueError("Completed quantity must be within the remaining work order quantity")

    consumed_components: list[dict[str, Any]] = []
    for component in existing.get("components", []):
        total_required = int(component.get("quantity_required", 0) or 0)
        consume_qty = round(total_required * (output_quantity / target_quantity))
        if consume_qty <= 0:
            continue
        sku_id = _parse_uuid(component.get("sku_id"))
        if sku_id is None:
            continue
        adjust_stage_inventory(
            store_id,
            sku_id,
            InventoryType.material,
            actor_user_id,
            delta_qty=-consume_qty,
            delta_allocated=-consume_qty,
            source=SupplyActionSource.system,
            reference_type="production_event",
            reference_id=work_order_id,
        )
        consumed_components.append(
            {
                "sku_id": str(sku_id),
                "quantity_required": consume_qty,
                "note": component.get("note"),
            }
        )

    adjust_stage_inventory(
        store_id,
        _parse_uuid(existing.get("finished_sku_id")) or uuid_mod.uuid4(),
        InventoryType.finished,
        actor_user_id,
        delta_qty=output_quantity,
        source=SupplyActionSource.system,
        reference_type="production_event",
        reference_id=work_order_id,
    )

    now = datetime.now(timezone.utc)
    new_completed_quantity = completed_quantity + output_quantity
    updated = update_document(
        work_order_collection(store_id),
        str(work_order_id),
        {
            "completed_quantity": new_completed_quantity,
            "status": (
                WorkOrderStatus.completed.value
                if new_completed_quantity >= target_quantity
                else WorkOrderStatus.in_progress.value
            ),
            "updated_by": str(actor_user_id),
            "updated_at": now,
            "note": payload.note or existing.get("note"),
        },
    )
    event_doc = create_document(
        production_event_collection(store_id),
        {
            "id": str(uuid_mod.uuid4()),
            "store_id": str(store_id),
            "work_order_id": str(work_order_id),
            "event_type": "completed",
            "output_quantity": output_quantity,
            "note": payload.note,
            "created_by": str(actor_user_id),
            "created_at": now,
            "consumed_components": consumed_components,
        },
    )
    return _to_work_order_read(updated, _load_sku_map(store_id)), _to_production_event_read(event_doc)


def list_production_events(store_id: UUID, *, work_order_id: UUID | None = None) -> list[ProductionEventRead]:
    docs = query_collection(production_event_collection(store_id), order_by="-created_at")
    rows = [_to_production_event_read(doc) for doc in docs]
    if work_order_id is not None:
        rows = [row for row in rows if row.work_order_id == work_order_id]
    return rows


def list_stock_transfers(
    store_id: UUID,
    *,
    status: TransferStatus | None = None,
) -> list[StockTransferRead]:
    sku_map = _load_sku_map(store_id)
    docs = query_collection(transfer_collection(store_id), order_by="-created_at")
    rows = [_to_transfer_read(doc, sku_map) for doc in docs]
    if status is not None:
        rows = [row for row in rows if row.status == status]
    return rows


def create_stock_transfer(store_id: UUID, payload: StockTransferCreate, actor_user_id: UUID) -> StockTransferRead:
    positions = {item.inventory_type: item for item in list_stage_inventory(store_id, sku_id=payload.sku_id)}
    current_source = positions.get(payload.from_inventory_type)
    if current_source is None:
        raise ValueError("No source inventory exists for this transfer")
    if current_source.available_quantity < payload.quantity:
        raise ValueError("Not enough available source inventory to dispatch this transfer")

    transfer_id = str(uuid_mod.uuid4())
    adjust_stage_inventory(
        store_id,
        payload.sku_id,
        payload.from_inventory_type,
        actor_user_id,
        delta_allocated=payload.quantity,
        source=payload.source,
        reference_type="stock_transfer",
        reference_id=UUID(transfer_id),
    )

    now = datetime.now(timezone.utc)
    doc = {
        "id": transfer_id,
        "store_id": str(store_id),
        "sku_id": str(payload.sku_id),
        "quantity": payload.quantity,
        "from_inventory_type": payload.from_inventory_type.value,
        "to_inventory_type": payload.to_inventory_type.value,
        "status": TransferStatus.in_transit.value,
        "note": payload.note,
        "source": payload.source.value,
        "recommendation_id": str(payload.recommendation_id) if payload.recommendation_id else None,
        "dispatched_at": now,
        "received_at": None,
        "created_by": str(actor_user_id),
        "updated_by": str(actor_user_id),
        "received_by": None,
        "created_at": now,
        "updated_at": now,
    }
    created = create_document(transfer_collection(store_id), doc, doc_id=transfer_id)
    return _to_transfer_read(created, _load_sku_map(store_id))


def receive_stock_transfer(
    store_id: UUID,
    transfer_id: UUID,
    payload: StockTransferReceiveRequest,
    actor_user_id: UUID,
) -> StockTransferRead:
    existing = get_document(transfer_collection(store_id), str(transfer_id))
    if existing is None:
        raise ValueError("Transfer not found")
    if existing.get("status") != TransferStatus.in_transit.value:
        raise ValueError("Only in-transit transfers can be received")

    sku_id = _parse_uuid(existing.get("sku_id"))
    if sku_id is None:
        raise ValueError("Transfer is missing its SKU")
    quantity = int(existing.get("quantity", 0) or 0)
    from_type = InventoryType(existing.get("from_inventory_type", InventoryType.purchased.value))
    to_type = InventoryType(existing.get("to_inventory_type", InventoryType.finished.value))

    adjust_stage_inventory(
        store_id,
        sku_id,
        from_type,
        actor_user_id,
        delta_qty=-quantity,
        delta_allocated=-quantity,
        source=SupplyActionSource.system,
        reference_type="stock_transfer",
        reference_id=transfer_id,
    )
    adjust_stage_inventory(
        store_id,
        sku_id,
        to_type,
        actor_user_id,
        delta_qty=quantity,
        source=SupplyActionSource.system,
        reference_type="stock_transfer",
        reference_id=transfer_id,
    )

    now = datetime.now(timezone.utc)
    updated = update_document(
        transfer_collection(store_id),
        str(transfer_id),
        {
            "status": TransferStatus.received.value,
            "note": payload.note or existing.get("note"),
            "received_at": now,
            "received_by": str(actor_user_id),
            "updated_by": str(actor_user_id),
            "updated_at": now,
        },
    )
    return _to_transfer_read(updated, _load_sku_map(store_id))
