from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.routers import manager_copilot, supply_chain
from app.schemas.copilot import (
    AuditSource,
    InventoryInsightRead,
    ManagerSummaryRead,
    RecommendationPublicRead,
    RecommendationStatus,
    RecommendationType,
)
from app.schemas.inventory import InventoryType, SourcingStrategy
from app.schemas.supply_chain import SupplyChainSummaryRead


def build_app(user_payload: dict) -> TestClient:
    app = FastAPI()
    app.include_router(manager_copilot.router)
    app.include_router(supply_chain.router)

    async def override_current_user():
        return user_payload

    app.dependency_overrides[get_current_user] = override_current_user
    return TestClient(app)


def test_staff_user_cannot_access_manager_copilot_or_supply_chain_routes():
    store_id = uuid4()
    staff_client = build_app(
        {
            "id": uuid4(),
            "store_roles": [
                {
                    "id": str(uuid4()),
                    "store_id": store_id,
                    "role": "staff",
                    "user_id": uuid4(),
                }
            ],
        }
    )

    copilot_response = staff_client.get(f"/api/stores/{store_id}/copilot/summary")
    supply_chain_response = staff_client.get(f"/api/stores/{store_id}/supply-chain/summary")

    assert copilot_response.status_code == 403
    assert supply_chain_response.status_code == 403


def test_sales_manager_keeps_copilot_access_but_cannot_access_supply_chain(monkeypatch):
    store_id = uuid4()
    sku_id = uuid4()

    monkeypatch.setattr(
        manager_copilot,
        "manager_summary",
        lambda _store_id: ManagerSummaryRead(
            store_id=_store_id,
            analysis_status="ready",
            low_stock_count=2,
            anomaly_count=1,
            pending_price_recommendations=1,
            pending_reorder_recommendations=1,
            pending_stock_anomalies=0,
            open_purchase_orders=4,
            active_work_orders=3,
            in_transit_transfers=2,
            purchased_units=25,
            material_units=11,
            finished_units=7,
            recent_outcomes=[],
        ),
    )
    monkeypatch.setattr(
        manager_copilot,
        "list_inventory_insights",
        lambda *_args, **_kwargs: [
            InventoryInsightRead(
                sku_id=sku_id,
                store_id=store_id,
                sku_code="SKU-001",
                description="Signature piece",
                inventory_type=InventoryType.finished,
                sourcing_strategy=SourcingStrategy.supplier_premade,
                supplier_name="GemCo",
                cost_price=150,
                purchased_qty=8,
                purchased_incoming_qty=3,
                material_qty=4,
                material_incoming_qty=2,
                material_allocated_qty=1,
                finished_qty=6,
                finished_allocated_qty=1,
                in_transit_qty=2,
                active_work_order_count=1,
                qty_on_hand=6,
                reorder_level=4,
                reorder_qty=8,
                low_stock=False,
                anomaly_flag=False,
            )
        ],
    )
    monkeypatch.setattr(
        supply_chain,
        "supply_chain_summary",
        lambda _store_id: SupplyChainSummaryRead(store_id=_store_id, supplier_count=3),
    )

    manager_client = build_app(
        {
            "id": uuid4(),
            "store_roles": [
                {
                    "id": str(uuid4()),
                    "store_id": store_id,
                    "role": "manager",
                    "user_id": uuid4(),
                }
            ],
        }
    )

    summary_response = manager_client.get(f"/api/stores/{store_id}/copilot/summary")
    inventory_response = manager_client.get(f"/api/stores/{store_id}/copilot/inventory")
    supply_chain_response = manager_client.get(f"/api/stores/{store_id}/supply-chain/summary")

    assert summary_response.status_code == 200
    summary_payload = summary_response.json()["data"]
    assert summary_payload["finished_units"] == 7
    assert summary_payload["open_purchase_orders"] == 0
    assert summary_payload["purchased_units"] == 0

    assert inventory_response.status_code == 200
    insight_payload = inventory_response.json()["data"][0]
    assert insight_payload["supplier_name"] is None
    assert insight_payload["cost_price"] is None
    assert insight_payload["purchased_qty"] == 0
    assert insight_payload["material_qty"] == 0
    assert insight_payload["qty_on_hand"] == 6

    assert supply_chain_response.status_code == 403


def test_owner_director_keeps_supply_chain_and_sensitive_copilot_fields(monkeypatch):
    store_id = uuid4()
    sku_id = uuid4()
    recommendation_id = uuid4()

    monkeypatch.setattr(
        manager_copilot,
        "list_recommendations",
        lambda *_args, **_kwargs: [
            RecommendationPublicRead(
                id=recommendation_id,
                store_id=store_id,
                sku_id=sku_id,
                inventory_type=InventoryType.finished,
                sourcing_strategy=SourcingStrategy.supplier_premade,
                supplier_name="GemCo",
                type=RecommendationType.reorder,
                status=RecommendationStatus.pending,
                title="Reorder signature piece",
                rationale="Demand is trending above the current store level.",
                confidence=0.88,
                supporting_metrics={"supplier_name": "GemCo", "unit_cost": 120},
                source=AuditSource.multica_recommendation,
                analysis_status="completed",
                generated_at=datetime.now(timezone.utc),
            )
        ],
    )
    monkeypatch.setattr(
        supply_chain,
        "supply_chain_summary",
        lambda _store_id: SupplyChainSummaryRead(
            store_id=_store_id,
            supplier_count=3,
            open_purchase_orders=2,
            finished_units=10,
        ),
    )

    owner_client = build_app(
        {
            "id": uuid4(),
            "store_roles": [
                {
                    "id": str(uuid4()),
                    "store_id": store_id,
                    "role": "owner",
                    "user_id": uuid4(),
                }
            ],
        }
    )

    recommendation_response = owner_client.get(f"/api/stores/{store_id}/copilot/recommendations")
    supply_chain_response = owner_client.get(f"/api/stores/{store_id}/supply-chain/summary")

    assert recommendation_response.status_code == 200
    recommendation_payload = recommendation_response.json()["data"][0]
    assert recommendation_payload["supplier_name"] == "GemCo"
    assert recommendation_payload["supporting_metrics"]["unit_cost"] == 120

    assert supply_chain_response.status_code == 200
    assert supply_chain_response.json()["data"]["supplier_count"] == 3
