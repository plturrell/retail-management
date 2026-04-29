from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from app.schemas.inventory import InventoryType, SourcingStrategy
from app.schemas.supply_chain import SupplyActionSource
from app.services import ai_analytics as analytics
from app.services import supply_chain as sc

from firestore_memory import MemoryFirestore


@pytest.fixture()
def memory(monkeypatch: pytest.MonkeyPatch) -> MemoryFirestore:
    store = MemoryFirestore()
    for name in ("get_document", "query_collection"):
        monkeypatch.setattr(analytics, name, getattr(store, name))
    for name in ("create_document", "get_document", "query_collection", "update_document"):
        monkeypatch.setattr(sc, name, getattr(store, name))
    return store


@pytest.mark.asyncio
async def test_margin_analysis_reads_store_scoped_catalog_and_prices(memory: MemoryFirestore):
    store_id = uuid4()
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
            "cost_price": 12,
        },
    )
    memory.seed(
        f"stores/{store_id}/prices",
        {
            "id": str(uuid4()),
            "sku_id": str(sku_id),
            "store_id": str(store_id),
            "price_incl_tax": 24,
            "valid_from": date(2026, 4, 1).isoformat(),
        },
    )
    memory.seed(
        f"stores/{store_id}/orders",
        {
            "id": str(uuid4()),
            "store_id": str(store_id),
            "order_date": date(2026, 4, 10).isoformat(),
            "status": "open",
            "grand_total": 24,
            "items": [
                {
                    "sku_id": str(sku_id),
                    "qty": 1,
                    "line_total": 24,
                }
            ],
        },
    )

    items = await analytics.compute_margin_analysis(
        store_id,
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 15),
    )

    assert len(items) == 1
    assert items[0].sku_code == "PRE-001"
    assert items[0].selling_price == 24
    assert items[0].total_profit == 12


@pytest.mark.asyncio
async def test_generate_insights_counts_out_of_stock_from_finished_stage(memory: MemoryFirestore):
    store_id = uuid4()
    actor_id = uuid4()
    sku_id = uuid4()

    memory.seed(
        sc.sku_collection(store_id),
        {
            "id": str(sku_id),
            "store_id": str(store_id),
            "sku_code": "PRE-002",
            "description": "Out of stock pendant",
            "inventory_type": InventoryType.finished.value,
            "sourcing_strategy": SourcingStrategy.supplier_premade.value,
            "cost_price": 14,
        },
    )
    memory.seed(
        sc.stock_collection(store_id),
        {
            "id": str(uuid4()),
            "sku_id": str(sku_id),
            "store_id": str(store_id),
            "qty_on_hand": 7,
            "reorder_level": 2,
            "reorder_qty": 5,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        },
    )
    sc.ensure_finished_stage_inventory(store_id, sku_id, actor_id)

    insights = await analytics.generate_insights(store_id, margins=[], trends=[], forecasts=[])

    inventory_insights = [item for item in insights if item.category == "inventory"]
    assert inventory_insights == []

    sc.adjust_stage_inventory(
        store_id,
        sku_id,
        InventoryType.finished,
        actor_id,
        delta_qty=-7,
        source=SupplyActionSource.system,
        reference_type="sell_down",
    )

    insights = await analytics.generate_insights(store_id, margins=[], trends=[], forecasts=[])

    inventory_insights = [item for item in insights if item.category == "inventory"]
    assert len(inventory_insights) == 1
    assert inventory_insights[0].title == "1 SKUs out of stock"
