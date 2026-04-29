from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from app.schemas.inventory import InventoryType, SourcingStrategy
from app.schemas.supply_chain import (
    BOMComponentInput,
    BOMRecipeCreate,
    PurchaseOrderCreate,
    PurchaseOrderReceiveLine,
    PurchaseOrderReceiveRequest,
    StockTransferCreate,
    StockTransferReceiveRequest,
    SupplierCreate,
    SupplyActionSource,
    WorkOrderCompleteRequest,
    WorkOrderCreate,
    WorkOrderType,
)
from app.services import supply_chain as sc

from firestore_memory import MemoryFirestore


@pytest.fixture()
def memory(monkeypatch: pytest.MonkeyPatch) -> MemoryFirestore:
    store = MemoryFirestore()
    for name in ("create_document", "get_document", "query_collection", "update_document"):
        monkeypatch.setattr(sc, name, getattr(store, name))
    return store


def seed_skus(memory: MemoryFirestore, store_id):
    material_id = uuid4()
    manufactured_finished_id = uuid4()
    premade_finished_id = uuid4()
    memory.seed(
        sc.sku_collection(store_id),
        {
            "id": str(material_id),
            "store_id": str(store_id),
            "sku_code": "MAT-001",
            "description": "Sterling silver grain",
            "inventory_type": InventoryType.material.value,
            "sourcing_strategy": SourcingStrategy.supplier_premade.value,
            "supplier_name": "MetalWorks",
            "cost_price": 4.5,
        },
        {
            "id": str(manufactured_finished_id),
            "store_id": str(store_id),
            "sku_code": "FIN-001",
            "description": "Silver ring",
            "inventory_type": InventoryType.finished.value,
            "sourcing_strategy": SourcingStrategy.manufactured_standard.value,
            "cost_price": 22,
        },
        {
            "id": str(premade_finished_id),
            "store_id": str(store_id),
            "sku_code": "PRE-001",
            "description": "Supplier pendant",
            "inventory_type": InventoryType.finished.value,
            "sourcing_strategy": SourcingStrategy.supplier_premade.value,
            "supplier_name": "GemCo",
            "cost_price": 12,
        },
    )
    return material_id, manufactured_finished_id, premade_finished_id


def stage_lookup(store_id, sku_id):
    return {
        item.inventory_type: item
        for item in sc.list_stage_inventory(store_id, sku_id=sku_id)
    }


def test_purchase_receipt_and_transfer_update_stage_ledgers(memory: MemoryFirestore):
    store_id = uuid4()
    actor_id = uuid4()
    _material_id, _manufactured_finished_id, premade_finished_id = seed_skus(memory, store_id)

    supplier = sc.create_supplier(
        store_id,
        SupplierCreate(name="GemCo", lead_time_days=5, currency="SGD"),
        actor_id,
    )
    purchase_order = sc.create_purchase_order(
        store_id,
        PurchaseOrderCreate(
            supplier_id=supplier.id,
            lines=[
                {
                    "sku_id": premade_finished_id,
                    "quantity": 5,
                    "unit_cost": 10,
                    "note": "Pilot replenishment",
                }
            ],
            expected_delivery_date=date(2026, 4, 20),
            note="Initial PO",
            source=SupplyActionSource.manual,
        ),
        actor_id,
    )

    before_receipt = stage_lookup(store_id, premade_finished_id)
    assert before_receipt[InventoryType.purchased].incoming_quantity == 5
    assert before_receipt[InventoryType.purchased].quantity_on_hand == 0

    received_order, _receipt = sc.receive_purchase_order(
        store_id,
        purchase_order.id,
        PurchaseOrderReceiveRequest(
            lines=[
                PurchaseOrderReceiveLine(
                    line_id=purchase_order.lines[0].line_id,
                    quantity_received=5,
                )
            ],
            note="Supplier truck arrived",
        ),
        actor_id,
    )

    assert received_order.status.value == "received"
    after_receipt = stage_lookup(store_id, premade_finished_id)
    assert after_receipt[InventoryType.purchased].quantity_on_hand == 5
    assert after_receipt[InventoryType.purchased].incoming_quantity == 0
    assert after_receipt[InventoryType.purchased].available_quantity == 5

    transfer = sc.create_stock_transfer(
        store_id,
        StockTransferCreate(
            sku_id=premade_finished_id,
            quantity=3,
            from_inventory_type=InventoryType.purchased,
            to_inventory_type=InventoryType.finished,
            note="Move sellable stock to store floor",
            source=SupplyActionSource.manual,
        ),
        actor_id,
    )
    assert transfer.status.value == "in_transit"

    received_transfer = sc.receive_stock_transfer(
        store_id,
        transfer.id,
        StockTransferReceiveRequest(note="Delivered to retail floor"),
        actor_id,
    )
    assert received_transfer.status.value == "received"

    positions = stage_lookup(store_id, premade_finished_id)
    assert positions[InventoryType.purchased].quantity_on_hand == 2
    assert positions[InventoryType.purchased].allocated_quantity == 0
    assert positions[InventoryType.finished].quantity_on_hand == 3
    stock_rows = memory.query_collection(sc.stock_collection(store_id), filters=(("sku_id", "==", str(premade_finished_id)),))
    assert stock_rows[0]["qty_on_hand"] == 3

    summary = sc.supply_chain_summary(store_id)
    assert summary.open_purchase_orders == 0
    assert summary.in_transit_transfers == 0
    assert summary.finished_units == 3


def test_work_order_completion_consumes_material_and_builds_finished_goods(
    memory: MemoryFirestore,
):
    store_id = uuid4()
    actor_id = uuid4()
    material_id, manufactured_finished_id, _premade_finished_id = seed_skus(memory, store_id)

    sc.adjust_stage_inventory(
        store_id,
        material_id,
        InventoryType.material,
        actor_id,
        delta_qty=10,
        sourcing_strategy=SourcingStrategy.supplier_premade,
        source=SupplyActionSource.manual,
        reference_type="seed",
    )

    recipe = sc.create_bom_recipe(
        store_id,
        BOMRecipeCreate(
            finished_sku_id=manufactured_finished_id,
            name="Ring Standard BOM",
            yield_quantity=1,
            components=[
                BOMComponentInput(
                    sku_id=material_id,
                    quantity_required=2,
                    note="Two units of silver grain per ring",
                )
            ],
            notes="Pilot BOM",
        ),
        actor_id,
    )

    work_order = sc.create_work_order(
        store_id,
        WorkOrderCreate(
            finished_sku_id=manufactured_finished_id,
            target_quantity=3,
            bom_id=recipe.id,
            work_order_type=WorkOrderType.standard,
            due_date=date(2026, 4, 22),
            note="Build three rings",
            source=SupplyActionSource.manual,
        ),
        actor_id,
    )
    allocated_stage = stage_lookup(store_id, material_id)[InventoryType.material]
    assert allocated_stage.allocated_quantity == 6
    assert allocated_stage.available_quantity == 4

    started = sc.start_work_order(store_id, work_order.id, actor_id)
    assert started.status.value == "in_progress"

    completed_order, production_event = sc.complete_work_order(
        store_id,
        work_order.id,
        WorkOrderCompleteRequest(completed_quantity=3, note="Manufacturing complete"),
        actor_id,
    )

    assert completed_order.status.value == "completed"
    assert completed_order.completed_quantity == 3
    assert production_event.output_quantity == 3
    assert production_event.consumed_components[0].quantity_required == 6

    material_stage = stage_lookup(store_id, material_id)[InventoryType.material]
    finished_stage = stage_lookup(store_id, manufactured_finished_id)[InventoryType.finished]
    assert material_stage.quantity_on_hand == 4
    assert material_stage.allocated_quantity == 0
    assert finished_stage.quantity_on_hand == 3

    stock_rows = memory.query_collection(
        sc.stock_collection(store_id),
        filters=(("sku_id", "==", str(manufactured_finished_id)),),
    )
    assert stock_rows[0]["qty_on_hand"] == 3

    production_events = sc.list_production_events(store_id, work_order_id=work_order.id)
    assert [event.event_type for event in production_events] == ["completed", "started", "scheduled"]


def test_stage_inventory_listing_does_not_synthesize_from_legacy_stock_rows(
    memory: MemoryFirestore,
):
    store_id = uuid4()
    actor_id = uuid4()
    _material_id, _manufactured_finished_id, premade_finished_id = seed_skus(memory, store_id)

    memory.seed(
        sc.stock_collection(store_id),
        {
            "id": str(uuid4()),
            "sku_id": str(premade_finished_id),
            "store_id": str(store_id),
            "qty_on_hand": 7,
            "reorder_level": 4,
            "reorder_qty": 6,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        },
    )

    assert sc.list_stage_inventory(store_id, sku_id=premade_finished_id) == []

    bootstrapped = sc.ensure_finished_stage_inventory(store_id, premade_finished_id, actor_id)

    assert bootstrapped is not None
    assert bootstrapped.inventory_type == InventoryType.finished
    assert bootstrapped.quantity_on_hand == 7
    assert sc.list_stage_inventory(store_id, sku_id=premade_finished_id)[0].quantity_on_hand == 7
