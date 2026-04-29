from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.schemas.inventory import InventoryType, SourcingStrategy
from app.schemas.supply_chain import SupplyActionSource
from app.services import inventory_logic as inventory
from app.services import supply_chain as sc

from firestore_memory import MemoryFirestore


@pytest.fixture()
def memory(monkeypatch: pytest.MonkeyPatch) -> MemoryFirestore:
    store = MemoryFirestore()
    for name in ("get_document", "query_collection", "update_document"):
        monkeypatch.setattr(inventory, name, getattr(store, name))
    for name in ("create_document", "get_document", "query_collection", "update_document"):
        monkeypatch.setattr(sc, name, getattr(store, name))
    return store


@pytest.mark.asyncio
async def test_reorder_recommendations_use_finished_stage_quantity(memory: MemoryFirestore):
    store_id = uuid4()
    actor_id = uuid4()
    sku_id = uuid4()

    memory.seed(
        sc.sku_collection(store_id),
        {
            "id": str(sku_id),
            "store_id": str(store_id),
            "sku_code": "PRE-001",
            "description": "Supplier pendant",
            "inventory_type": InventoryType.finished.value,
            "sourcing_strategy": SourcingStrategy.supplier_premade.value,
            "supplier_name": "GemCo",
            "cost_price": 12,
        },
    )
    memory.seed(
        sc.stock_collection(store_id),
        {
            "id": str(uuid4()),
            "sku_id": str(sku_id),
            "store_id": str(store_id),
            "qty_on_hand": 9,
            "reorder_level": 4,
            "reorder_qty": 6,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        },
    )
    sc.adjust_stage_inventory(
        store_id,
        sku_id,
        InventoryType.finished,
        actor_id,
        delta_qty=1,
        source=SupplyActionSource.system,
        reference_type="seed",
    )
    stock_row = memory.query_collection(
        sc.stock_collection(store_id),
        filters=(("sku_id", "==", str(sku_id)),),
        limit=1,
    )[0]
    memory.update_document(
        sc.stock_collection(store_id),
        str(stock_row["id"]),
        {
            "qty_on_hand": 9,
            "updated_at": datetime.now(timezone.utc),
        },
    )

    recommendations = await inventory.reorder_recommendations(store_id, lookback_days=30)

    assert len(recommendations) == 1
    assert recommendations[0]["sku_id"] == str(sku_id)
    assert recommendations[0]["qty_on_hand"] == 1
    assert recommendations[0]["reorder_level"] == 4
    assert recommendations[0]["recommended_order_qty"] == 6
