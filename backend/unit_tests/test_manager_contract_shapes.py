from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.schemas.copilot import (
    RecommendationPublicRead,
    RecommendationTriggerRequest,
)
from app.schemas.inventory import InventoryType, SourcingStrategy
from app.schemas.supply_chain import SupplierCreate, SupplyActionSource
from app.services import manager_copilot as copilot
from app.services import supply_chain as sc
from app.services.multica_client import MulticaResponse

from firestore_memory import MemoryFirestore


@pytest.fixture()
def memory(monkeypatch: pytest.MonkeyPatch) -> MemoryFirestore:
    store = MemoryFirestore()
    for module in (sc, copilot):
        for name in ("create_document", "get_document", "query_collection", "update_document"):
            monkeypatch.setattr(module, name, getattr(store, name))

    async def fake_multica(*_args, **_kwargs):
        return MulticaResponse(
            model_used="fallback",
            raw_text="offline",
            payload={"status": "offline", "critical_skus": []},
        )

    async def no_op_notify(*_args, **_kwargs):
        return None

    monkeypatch.setattr(copilot, "analyze_inventory_health", fake_multica)
    monkeypatch.setattr(copilot, "_maybe_notify_opensclaw", no_op_notify)
    return store


def seed_store(memory: MemoryFirestore, store_id):
    sku_id = uuid4()
    inventory_id = uuid4()
    memory.seed(
        copilot.sku_collection(store_id),
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
        copilot.stock_collection(store_id),
        {
            "id": str(inventory_id),
            "sku_id": str(sku_id),
            "store_id": str(store_id),
            "qty_on_hand": 1,
            "reorder_level": 4,
            "reorder_qty": 6,
            "last_updated": datetime.now(timezone.utc),
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        },
    )
    sc.adjust_stage_inventory(
        store_id,
        sku_id,
        InventoryType.finished,
        uuid4(),
        delta_qty=1,
        source=SupplyActionSource.system,
        reference_type="seed",
    )
    return sku_id


@pytest.mark.asyncio
async def test_public_manager_contract_shapes_match_the_canonical_pilot_schema(
    memory: MemoryFirestore,
):
    store_id = uuid4()
    actor_id = uuid4()
    seed_store(memory, store_id)
    sc.create_supplier(store_id, SupplierCreate(name="GemCo", currency="SGD"), actor_id)

    trigger = await copilot.trigger_analysis(
        store_id,
        actor_id,
        RecommendationTriggerRequest(force_refresh=True, lookback_days=30, low_stock_threshold=5),
    )

    recommendation_payload = RecommendationPublicRead.model_validate(
        trigger.recommendations[0].model_dump(mode="python")
    ).model_dump(mode="json")
    summary_payload = copilot.manager_summary(store_id).model_dump(mode="json")
    insight_payload = copilot.list_inventory_insights(store_id)[0].model_dump(mode="json")
    supply_payload = sc.supply_chain_summary(store_id).model_dump(mode="json")

    assert set(recommendation_payload.keys()) == {
        "id",
        "store_id",
        "sku_id",
        "inventory_id",
        "inventory_type",
        "sourcing_strategy",
        "supplier_name",
        "type",
        "status",
        "title",
        "rationale",
        "confidence",
        "supporting_metrics",
        "source",
        "expected_impact",
        "current_price",
        "suggested_price",
        "suggested_order_qty",
        "workflow_action",
        "analysis_status",
        "generated_at",
        "decided_at",
        "applied_at",
        "note",
    }
    assert "created_at" not in recommendation_payload
    assert "updated_at" not in recommendation_payload
    assert "dedupe_key" not in recommendation_payload

    assert set(summary_payload.keys()) == {
        "store_id",
        "analysis_status",
        "last_generated_at",
        "low_stock_count",
        "anomaly_count",
        "pending_price_recommendations",
        "pending_reorder_recommendations",
        "pending_stock_anomalies",
        "open_purchase_orders",
        "active_work_orders",
        "in_transit_transfers",
        "purchased_units",
        "material_units",
        "finished_units",
        "recent_outcomes",
    }

    assert set(insight_payload.keys()) == {
        "inventory_id",
        "sku_id",
        "store_id",
        "sku_code",
        "description",
        "long_description",
        "inventory_type",
        "sourcing_strategy",
        "supplier_name",
        "cost_price",
        "current_price",
        "current_price_valid_until",
        "purchased_qty",
        "purchased_incoming_qty",
        "material_qty",
        "material_incoming_qty",
        "material_allocated_qty",
        "finished_qty",
        "finished_allocated_qty",
        "in_transit_qty",
        "active_work_order_count",
        "qty_on_hand",
        "reorder_level",
        "reorder_qty",
        "low_stock",
        "anomaly_flag",
        "anomaly_reason",
        "recent_sales_qty",
        "recent_sales_revenue",
        "avg_daily_sales",
        "days_of_cover",
        "pending_recommendation_count",
        "pending_price_recommendation_count",
        "last_updated",
    }

    assert set(supply_payload.keys()) == {
        "store_id",
        "supplier_count",
        "open_purchase_orders",
        "active_work_orders",
        "in_transit_transfers",
        "purchased_units",
        "material_units",
        "finished_units",
        "open_recommendation_linked_orders",
    }
