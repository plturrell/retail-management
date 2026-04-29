from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.schemas.copilot import (
    RecommendationApplyRequest,
    RecommendationDecisionRequest,
    RecommendationStatus,
    RecommendationTriggerRequest,
    RecommendationType,
)
from app.schemas.inventory import InventoryType, SourcingStrategy
from app.schemas.supply_chain import SupplyActionSource, SupplierCreate
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
    adjustment_id = uuid4()
    memory.seed(
        copilot.adjustment_collection(store_id),
        {
            "id": str(adjustment_id),
            "inventory_id": str(inventory_id),
            "sku_id": str(sku_id),
            "store_id": str(store_id),
            "quantity_delta": -1,
            "resulting_qty": 1,
            "reason": "Manual cycle count",
            "source": "manual",
            "note": "Counted on the sales floor",
            "created_at": datetime.now(timezone.utc),
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
    return sku_id, inventory_id


@pytest.mark.asyncio
async def test_trigger_analysis_dedupes_and_survives_multica_fallback(memory: MemoryFirestore):
    store_id = uuid4()
    actor_id = uuid4()
    sku_id, _inventory_id = seed_store(memory, store_id)
    sc.create_supplier(store_id, SupplierCreate(name="GemCo", currency="SGD"), actor_id)

    first = await copilot.trigger_analysis(
        store_id,
        actor_id,
        RecommendationTriggerRequest(force_refresh=False, lookback_days=30, low_stock_threshold=5),
    )

    assert first.analysis_status == "unavailable"
    assert first.multica_status == "offline"
    assert first.recommendations_created >= 1
    assert any(rec.type == RecommendationType.reorder for rec in first.recommendations)

    second = await copilot.trigger_analysis(
        store_id,
        actor_id,
        RecommendationTriggerRequest(force_refresh=False, lookback_days=30, low_stock_threshold=5),
    )

    assert second.recommendations_created == 0
    assert second.recommendations_reused >= 1
    reused = [rec for rec in second.recommendations if rec.sku_id == sku_id]
    assert reused

    adjustments = copilot.list_adjustments(store_id, sku_id=sku_id)
    assert adjustments[0].reason == "Manual cycle count"


@pytest.mark.asyncio
async def test_reject_then_apply_recommendation_uses_canonical_supply_chain_actions(
    memory: MemoryFirestore,
):
    store_id = uuid4()
    actor_id = uuid4()
    sku_id, _inventory_id = seed_store(memory, store_id)
    sc.create_supplier(store_id, SupplierCreate(name="GemCo", currency="SGD"), actor_id)

    first_batch = await copilot.trigger_analysis(
        store_id,
        actor_id,
        RecommendationTriggerRequest(force_refresh=True, lookback_days=30, low_stock_threshold=5),
    )
    first_reorder = next(rec for rec in first_batch.recommendations if rec.type == RecommendationType.reorder)

    rejected = copilot.reject_recommendation(
        store_id,
        first_reorder.id,
        actor_id,
        RecommendationDecisionRequest(note="Holding off until tomorrow."),
    )
    assert rejected.status == RecommendationStatus.rejected
    assert sc.list_purchase_orders(store_id) == []

    second_batch = await copilot.trigger_analysis(
        store_id,
        actor_id,
        RecommendationTriggerRequest(force_refresh=True, lookback_days=30, low_stock_threshold=5),
    )
    second_reorder = next(
        rec
        for rec in second_batch.recommendations
        if rec.type == RecommendationType.reorder and rec.id != first_reorder.id
    )

    approved = copilot.approve_recommendation(
        store_id,
        second_reorder.id,
        actor_id,
        RecommendationDecisionRequest(note="Manager approved."),
    )
    assert approved.status == RecommendationStatus.approved

    applied = copilot.apply_recommendation(
        store_id,
        second_reorder.id,
        actor_id,
        RecommendationApplyRequest(note="Create the supplier PO."),
    )
    assert applied.status == RecommendationStatus.applied

    purchase_orders = sc.list_purchase_orders(store_id)
    assert len(purchase_orders) == 1
    assert purchase_orders[0].recommendation_id == second_reorder.id
    assert purchase_orders[0].lines[0].sku_id == sku_id
    assert purchase_orders[0].source == SupplyActionSource.recommendation

    summary = copilot.manager_summary(store_id)
    assert summary.analysis_status == "unavailable"
    assert summary.open_purchase_orders == 1
    assert summary.pending_reorder_recommendations == 0


def test_inventory_insights_use_stage_ledger_quantity_over_legacy_stock_row(memory: MemoryFirestore):
    store_id = uuid4()
    sku_id, inventory_id = seed_store(memory, store_id)
    memory.update_document(
        copilot.stock_collection(store_id),
        str(inventory_id),
        {
            "qty_on_hand": 9,
            "updated_at": datetime.now(timezone.utc),
        },
    )

    insights = copilot.list_inventory_insights(store_id)

    assert len(insights) == 1
    assert insights[0].sku_id == sku_id
    assert insights[0].qty_on_hand == 1
    assert insights[0].finished_qty == 1
    assert insights[0].low_stock is True
