from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.routers import analytics
from app.services.staff_analytics import StaffInsightsResponse, StaffPerformanceItem, StaffPerformanceOverview


def build_app(user_payload: dict) -> TestClient:
    app = FastAPI()
    app.include_router(analytics.router)

    async def override_current_user():
        return user_payload

    app.dependency_overrides[get_current_user] = override_current_user
    return TestClient(app)


def _overview(store_id, staff_id, peer_id) -> StaffPerformanceOverview:
    return StaffPerformanceOverview(
        generated_at=datetime.now(timezone.utc).isoformat(),
        store_id=str(store_id),
        period_from="2026-04-01",
        period_to="2026-04-30",
        total_store_sales=300,
        staff=[
            StaffPerformanceItem(
                user_id=str(peer_id),
                full_name="Peer Staff",
                total_sales=200,
                order_count=2,
                avg_order_value=100,
                rank=1,
            ),
            StaffPerformanceItem(
                user_id=str(staff_id),
                full_name="Current Staff",
                total_sales=100,
                order_count=1,
                avg_order_value=100,
                rank=2,
            ),
        ],
    )


def test_staff_performance_returns_only_self_for_staff(monkeypatch):
    store_id = uuid4()
    staff_id = uuid4()
    peer_id = uuid4()

    async def fake_summary(*_args):
        return _overview(store_id, staff_id, peer_id)

    monkeypatch.setattr(analytics, "get_staff_sales_summary", fake_summary)

    client = build_app(
        {
            "id": staff_id,
            "store_roles": [{"id": str(uuid4()), "store_id": store_id, "role": "staff", "user_id": staff_id}],
        }
    )

    response = client.get(f"/api/stores/{store_id}/analytics/staff-performance?from=2026-04-01&to=2026-04-30")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_store_sales"] == 100
    assert [row["user_id"] for row in payload["staff"]] == [str(staff_id)]


def test_manager_performance_keeps_team_view(monkeypatch):
    store_id = uuid4()
    manager_id = uuid4()
    staff_id = uuid4()
    peer_id = uuid4()

    async def fake_summary(*_args):
        return _overview(store_id, staff_id, peer_id)

    monkeypatch.setattr(analytics, "get_staff_sales_summary", fake_summary)

    client = build_app(
        {
            "id": manager_id,
            "store_roles": [{"id": str(uuid4()), "store_id": store_id, "role": "manager", "user_id": manager_id}],
        }
    )

    response = client.get(f"/api/stores/{store_id}/analytics/staff-performance?from=2026-04-01&to=2026-04-30")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_store_sales"] == 300
    assert len(payload["staff"]) == 2


def test_staff_cannot_request_peer_insights(monkeypatch):
    store_id = uuid4()
    staff_id = uuid4()
    peer_id = uuid4()
    async def fake_insights(*_args):
        return StaffInsightsResponse(user_id=str(peer_id), full_name="Peer Staff", summary={})

    monkeypatch.setattr(analytics, "generate_staff_insights", fake_insights)

    client = build_app(
        {
            "id": staff_id,
            "store_roles": [{"id": str(uuid4()), "store_id": store_id, "role": "staff", "user_id": staff_id}],
        }
    )

    response = client.get(f"/api/stores/{store_id}/analytics/staff/{peer_id}/insights")

    assert response.status_code == 403
