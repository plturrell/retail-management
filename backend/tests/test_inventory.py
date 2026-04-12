from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import TestSessionLocal
from app.models.inventory import Brand, Category, Inventory, PLU, Price, SKU
from app.models.store import Store
from app.models.user import User


@pytest_asyncio.fixture
async def seed_store_and_user():
    """Create a store and user for tests."""
    async with TestSessionLocal() as session:
        store = Store(
            name="Victoria Enso Jewel",
            location="Jewel Changi Airport",
            address="#02-234 Jewel Changi Airport",
            business_hours_start=time(10, 0),
            business_hours_end=time(22, 0),
        )
        session.add(store)
        await session.flush()
        await session.refresh(store)

        user = User(
            firebase_uid="test-firebase-uid",
            email="test@example.com",
            full_name="Test User",
        )
        session.add(user)
        await session.commit()
        await session.refresh(store)
        await session.refresh(user)
        return store, user


@pytest_asyncio.fixture
async def seed_sku(seed_store_and_user):
    """Create a brand, category, and SKU for tests."""
    store, user = seed_store_and_user
    async with TestSessionLocal() as session:
        brand = Brand(name="Victoria Enso")
        session.add(brand)
        await session.flush()
        await session.refresh(brand)

        category = Category(
            catg_code="JWL001",
            description="Jewellery",
            store_id=store.id,
        )
        session.add(category)
        await session.flush()
        await session.refresh(category)

        sku = SKU(
            sku_code="VEJWL00000000001",
            description="Gold Ring 18K",
            cost_price=500.00,
            category_id=category.id,
            brand_id=brand.id,
            tax_code="G",
            is_unique_piece=True,
            use_stock=True,
            block_sales=False,
            store_id=store.id,
        )
        session.add(sku)
        await session.flush()
        await session.refresh(sku)
        await session.commit()
        return store, brand, category, sku


# ==================== SKU CRUD ====================

class TestSKUCRUD:
    @pytest.mark.asyncio
    async def test_create_sku(self, client: AsyncClient, seed_store_and_user):
        store, _ = seed_store_and_user
        payload = {
            "sku_code": "VEJWL00000000002",
            "description": "Silver Bracelet",
            "cost_price": 150.00,
            "tax_code": "G",
            "store_id": str(store.id),
        }
        resp = await client.post(f"/api/stores/{store.id}/skus", json=payload)
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["sku_code"] == "VEJWL00000000002"
        assert data["description"] == "Silver Bracelet"

    @pytest.mark.asyncio
    async def test_list_skus(self, client: AsyncClient, seed_sku):
        store, _, _, sku = seed_sku
        resp = await client.get(f"/api/stores/{store.id}/skus")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        codes = [s["sku_code"] for s in data["data"]]
        assert sku.sku_code in codes

    @pytest.mark.asyncio
    async def test_list_skus_search(self, client: AsyncClient, seed_sku):
        store, _, _, _ = seed_sku
        resp = await client.get(f"/api/stores/{store.id}/skus?search=Gold")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    @pytest.mark.asyncio
    async def test_get_sku(self, client: AsyncClient, seed_sku):
        store, _, _, sku = seed_sku
        resp = await client.get(f"/api/stores/{store.id}/skus/{sku.id}")
        assert resp.status_code == 200
        assert resp.json()["data"]["sku_code"] == sku.sku_code

    @pytest.mark.asyncio
    async def test_update_sku(self, client: AsyncClient, seed_sku):
        store, _, _, sku = seed_sku
        resp = await client.patch(
            f"/api/stores/{store.id}/skus/{sku.id}",
            json={"description": "Gold Ring 24K"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["description"] == "Gold Ring 24K"

    @pytest.mark.asyncio
    async def test_delete_sku(self, client: AsyncClient, seed_store_and_user):
        store, _ = seed_store_and_user
        # Create then delete
        payload = {
            "sku_code": "VEJWL00000000099",
            "description": "Delete Me",
            "tax_code": "G",
            "store_id": str(store.id),
        }
        create_resp = await client.post(f"/api/stores/{store.id}/skus", json=payload)
        sku_id = create_resp.json()["data"]["id"]

        del_resp = await client.delete(f"/api/stores/{store.id}/skus/{sku_id}")
        assert del_resp.status_code == 204

        get_resp = await client.get(f"/api/stores/{store.id}/skus/{sku_id}")
        assert get_resp.status_code == 404


# ==================== Barcode Lookup ====================

class TestBarcodeLookup:
    @pytest.mark.asyncio
    async def test_barcode_lookup(self, client: AsyncClient, seed_sku):
        store, _, _, sku = seed_sku

        # Create a PLU barcode
        async with TestSessionLocal() as session:
            plu = PLU(plu_code="8801234567890", sku_id=sku.id)
            session.add(plu)

            price = Price(
                sku_id=sku.id,
                store_id=store.id,
                price_incl_tax=1299.00,
                price_excl_tax=1214.95,
                price_unit=1,
                valid_from=date(2020, 1, 1),
                valid_to=date(2099, 12, 31),
            )
            session.add(price)
            await session.commit()

        resp = await client.get("/api/barcode/8801234567890")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["sku"]["sku_code"] == sku.sku_code
        assert data["current_price"] is not None
        assert float(data["current_price"]["price_incl_tax"]) == 1299.00

    @pytest.mark.asyncio
    async def test_barcode_not_found(self, client: AsyncClient, seed_store_and_user):
        resp = await client.get("/api/barcode/0000000000000")
        assert resp.status_code == 404


# ==================== Inventory Adjustment ====================

class TestInventoryAdjustment:
    @pytest.mark.asyncio
    async def test_adjust_inventory_add(self, client: AsyncClient, seed_sku):
        store, _, _, sku = seed_sku

        # Create inventory record
        inv_payload = {
            "sku_id": str(sku.id),
            "store_id": str(store.id),
            "qty_on_hand": 10,
            "reorder_level": 5,
            "reorder_qty": 20,
        }
        create_resp = await client.post(
            f"/api/stores/{store.id}/inventory", json=inv_payload
        )
        assert create_resp.status_code == 201
        inv_id = create_resp.json()["data"]["id"]

        # Adjust +5
        adj_resp = await client.post(
            f"/api/stores/{store.id}/inventory/{inv_id}/adjust",
            json={"quantity": 5, "reason": "Received shipment"},
        )
        assert adj_resp.status_code == 200
        assert adj_resp.json()["data"]["qty_on_hand"] == 15

    @pytest.mark.asyncio
    async def test_adjust_inventory_subtract(self, client: AsyncClient, seed_sku):
        store, _, _, sku = seed_sku

        inv_payload = {
            "sku_id": str(sku.id),
            "store_id": str(store.id),
            "qty_on_hand": 10,
            "reorder_level": 5,
            "reorder_qty": 20,
        }
        create_resp = await client.post(
            f"/api/stores/{store.id}/inventory", json=inv_payload
        )
        inv_id = create_resp.json()["data"]["id"]

        # Adjust -3
        adj_resp = await client.post(
            f"/api/stores/{store.id}/inventory/{inv_id}/adjust",
            json={"quantity": -3, "reason": "Sold"},
        )
        assert adj_resp.status_code == 200
        assert adj_resp.json()["data"]["qty_on_hand"] == 7

    @pytest.mark.asyncio
    async def test_adjust_inventory_negative_result(self, client: AsyncClient, seed_sku):
        store, _, _, sku = seed_sku

        inv_payload = {
            "sku_id": str(sku.id),
            "store_id": str(store.id),
            "qty_on_hand": 2,
            "reorder_level": 5,
            "reorder_qty": 20,
        }
        create_resp = await client.post(
            f"/api/stores/{store.id}/inventory", json=inv_payload
        )
        inv_id = create_resp.json()["data"]["id"]

        # Try to subtract more than available
        adj_resp = await client.post(
            f"/api/stores/{store.id}/inventory/{inv_id}/adjust",
            json={"quantity": -10, "reason": "Error test"},
        )
        assert adj_resp.status_code == 400


# ==================== Reorder Alerts ====================

class TestReorderAlerts:
    @pytest.mark.asyncio
    async def test_reorder_alerts(self, client: AsyncClient, seed_sku):
        store, _, _, sku = seed_sku

        # Create inventory at reorder level
        async with TestSessionLocal() as session:
            inv = Inventory(
                sku_id=sku.id,
                store_id=store.id,
                qty_on_hand=3,
                reorder_level=5,
                reorder_qty=20,
                last_updated=datetime.now(UTC),
            )
            session.add(inv)
            await session.commit()

        resp = await client.get(f"/api/stores/{store.id}/inventory/alerts")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) >= 1
        # All returned items should have qty_on_hand <= reorder_level
        for item in data:
            assert item["qty_on_hand"] <= item["reorder_level"]

    @pytest.mark.asyncio
    async def test_no_alerts_when_stocked(self, client: AsyncClient, seed_sku):
        store, _, _, sku = seed_sku

        # Create well-stocked inventory
        async with TestSessionLocal() as session:
            inv = Inventory(
                sku_id=sku.id,
                store_id=store.id,
                qty_on_hand=100,
                reorder_level=5,
                reorder_qty=20,
                last_updated=datetime.now(UTC),
            )
            session.add(inv)
            await session.commit()

        resp = await client.get(f"/api/stores/{store.id}/inventory/alerts")
        assert resp.status_code == 200
        # The well-stocked one should not appear in alerts
        data = resp.json()["data"]
        for item in data:
            assert item["qty_on_hand"] <= item["reorder_level"]
