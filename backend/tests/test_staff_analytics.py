"""Tests for staff performance analytics — data aggregation and AI insights."""
from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from httpx import AsyncClient

from app.models.order import Order, OrderItem, OrderSource, OrderStatus
from app.models.inventory import SKU
from app.models.store import Store
from app.models.user import User, UserStoreRole, RoleEnum
from tests.conftest import TestSessionLocal


async def _seed_store_and_user(seed_user):
    """Create a store and assign the test user as owner. Returns store."""
    async with TestSessionLocal() as session:
        store = Store(
            name="TEST-STORE",
            location="Test Location",
            address="123 Test St",
            business_hours_start=time(10, 0),
            business_hours_end=time(22, 0),
            is_active=True,
        )
        session.add(store)
        await session.flush()

        role = UserStoreRole(
            user_id=seed_user.id,
            store_id=store.id,
            role=RoleEnum.owner,
        )
        session.add(role)
        await session.commit()
        await session.refresh(store)
        return store


async def _seed_second_staff(store_id):
    """Create a second staff member for comparison tests."""
    async with TestSessionLocal() as session:
        user2 = User(
            firebase_uid="staff-2-uid",
            email="staff2@example.com",
            full_name="Staff Two",
        )
        session.add(user2)
        await session.flush()

        role = UserStoreRole(
            user_id=user2.id,
            store_id=store_id,
            role=RoleEnum.staff,
        )
        session.add(role)
        await session.commit()
        await session.refresh(user2)
        return user2


async def _seed_sku(store_id):
    """Create a test SKU."""
    async with TestSessionLocal() as session:
        sku = SKU(
            sku_code="TEST-SKU-001",
            description="Test Product",
            store_id=store_id,
            tax_code="G",
        )
        session.add(sku)
        await session.commit()
        await session.refresh(sku)
        return sku


async def _seed_orders(store_id, salesperson_id, sku_id, count=3, base_date=None):
    """Seed orders for a salesperson."""
    if base_date is None:
        base_date = datetime.now(timezone.utc) - timedelta(days=10)
    async with TestSessionLocal() as session:
        for i in range(count):
            order = Order(
                order_number=f"ORD-{uuid.uuid4().hex[:8]}",
                store_id=store_id,
                staff_id=salesperson_id,
                salesperson_id=salesperson_id,
                order_date=base_date + timedelta(days=i),
                subtotal=100.00 * (i + 1),
                discount_total=0,
                tax_total=7.00 * (i + 1),
                grand_total=107.00 * (i + 1),
                payment_method="cash",
                status=OrderStatus.completed,
                source=OrderSource.manual,
            )
            session.add(order)
            await session.flush()

            item = OrderItem(
                order_id=order.id,
                sku_id=sku_id,
                qty=i + 1,
                unit_price=100.00,
                discount=0,
                line_total=100.00 * (i + 1),
            )
            session.add(item)
        await session.commit()



# ──────────────────── Tests ──────────────────────────────


@pytest.mark.asyncio
async def test_staff_performance_endpoint(client: AsyncClient, seed_user):
    """Staff performance endpoint returns ranking with sales data."""
    store = await _seed_store_and_user(seed_user)
    sku = await _seed_sku(store.id)
    staff2 = await _seed_second_staff(store.id)

    # Seed orders for both staff
    await _seed_orders(store.id, seed_user.id, sku.id, count=3)
    await _seed_orders(store.id, staff2.id, sku.id, count=2)

    today = datetime.now(timezone.utc).date()
    from_date = (today - timedelta(days=30)).isoformat()
    to_date = today.isoformat()

    resp = await client.get(
        f"/api/stores/{store.id}/analytics/staff-performance",
        params={"from": from_date, "to": to_date},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["store_id"] == str(store.id)
    assert len(data["staff"]) == 2
    # First ranked should have higher total_sales
    assert data["staff"][0]["rank"] == 1
    assert data["staff"][0]["total_sales"] >= data["staff"][1]["total_sales"]
    assert data["total_store_sales"] > 0


@pytest.mark.asyncio
async def test_staff_performance_empty(client: AsyncClient, seed_user):
    """Staff performance returns empty list when no orders exist."""
    store = await _seed_store_and_user(seed_user)

    today = datetime.now(timezone.utc).date()
    resp = await client.get(
        f"/api/stores/{store.id}/analytics/staff-performance",
        params={"from": (today - timedelta(days=7)).isoformat(), "to": today.isoformat()},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["staff"] == []
    assert data["total_store_sales"] == 0


@pytest.mark.asyncio
async def test_staff_insights_endpoint(client: AsyncClient, seed_user):
    """Staff insights endpoint returns summary and AI insights (mocked)."""
    store = await _seed_store_and_user(seed_user)
    sku = await _seed_sku(store.id)
    await _seed_orders(store.id, seed_user.id, sku.id, count=5)

    mock_resp = MagicMock()
    mock_resp.text = "This staff member shows strong performance."
    mock_resp.is_fallback = False

    with patch("app.services.ai_gateway.invoke", return_value=mock_resp):
        resp = await client.get(
            f"/api/stores/{store.id}/analytics/staff/{seed_user.id}/insights",
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == str(seed_user.id)
    assert data["full_name"] == "Test User"
    assert data["summary"]["total_sales"] > 0
    assert data["ai_insights"] == "This staff member shows strong performance."


@pytest.mark.asyncio
async def test_staff_insights_gemini_fallback(client: AsyncClient, seed_user):
    """Staff insights returns null ai_insights when Gemini is unavailable."""
    store = await _seed_store_and_user(seed_user)
    sku = await _seed_sku(store.id)
    await _seed_orders(store.id, seed_user.id, sku.id, count=2)

    mock_resp = MagicMock()
    mock_resp.text = ""
    mock_resp.is_fallback = True

    with patch("app.services.ai_gateway.invoke", return_value=mock_resp):
        resp = await client.get(
            f"/api/stores/{store.id}/analytics/staff/{seed_user.id}/insights",
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ai_insights"] is None
    assert data["summary"]["order_count"] > 0


@pytest.mark.asyncio
async def test_scheduling_recommendations_endpoint(client: AsyncClient, seed_user):
    """Scheduling recommendations returns day-of-week data with AI summary."""
    store = await _seed_store_and_user(seed_user)
    sku = await _seed_sku(store.id)

    # Seed orders across multiple days
    for day_offset in range(0, 14):
        base = datetime.now(timezone.utc) - timedelta(days=day_offset)
        await _seed_orders(store.id, seed_user.id, sku.id, count=1, base_date=base)

    mock_resp = MagicMock()
    mock_resp.text = "Schedule more staff on weekends."
    mock_resp.is_fallback = False

    with patch("app.services.ai_gateway.invoke", return_value=mock_resp):
        resp = await client.get(
            f"/api/stores/{store.id}/analytics/scheduling-recommendations",
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["store_id"] == str(store.id)
    assert len(data["recommendations"]) == 7
    days = [r["day_of_week"] for r in data["recommendations"]]
    assert "Monday" in days
    assert "Sunday" in days
    assert data["ai_summary"] == "Schedule more staff on weekends."
    for rec in data["recommendations"]:
        assert rec["recommended_staff_count"] >= 1