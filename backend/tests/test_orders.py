from __future__ import annotations

import io
import uuid
from datetime import datetime, time, timezone

import pytest
from httpx import AsyncClient

from app.models.inventory import SKU, Category, Brand
from app.models.order import Order, OrderItem, OrderSource, OrderStatus
from app.models.store import Store
from app.models.user import UserStoreRole, RoleEnum
from tests.conftest import TestSessionLocal


async def _seed_store_and_user(seed_user):
    """Create a store and assign the test user as owner. Returns store."""
    async with TestSessionLocal() as session:
        store = Store(
            name="JEWEL-B1-241",
            location="Jewel Changi Airport",
            address="78 Airport Blvd, #B1-241",
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


async def _seed_sku(store_id, category_id=None, brand_id=None, sku_code="VE-JWL-001"):
    """Create a SKU for testing. Returns SKU."""
    async with TestSessionLocal() as session:
        sku = SKU(
            sku_code=sku_code,
            description="Test Product",
            store_id=store_id,
            tax_code="G",
            category_id=category_id,
            brand_id=brand_id,
        )
        session.add(sku)
        await session.commit()
        await session.refresh(sku)
        return sku


async def _seed_category(store_id):
    """Create a category for testing."""
    async with TestSessionLocal() as session:
        cat = Category(
            catg_code="JWLRY",
            description="Jewellery",
            store_id=store_id,
        )
        session.add(cat)
        await session.commit()
        await session.refresh(cat)
        return cat


async def _seed_brand():
    """Create a brand for testing."""
    async with TestSessionLocal() as session:
        brand = Brand(
            name="Victoria Enso",
        )
        session.add(brand)
        await session.commit()
        await session.refresh(brand)
        return brand


# ─── Test Order CRUD ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_order_with_line_items(client: AsyncClient, seed_user):
    store = await _seed_store_and_user(seed_user)
    sku = await _seed_sku(store.id)

    payload = {
        "store_id": str(store.id),
        "payment_method": "nets",
        "source": "manual",
        "items": [
            {
                "sku_id": str(sku.id),
                "qty": 2,
                "unit_price": 150.00,
                "discount": 0,
                "line_total": 300.00,
            }
        ],
    }

    resp = await client.post(f"/api/stores/{store.id}/orders", json=payload)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["success"] is True
    order = data["data"]
    assert order["source"] == "manual"
    assert order["payment_method"] == "nets"
    assert len(order["items"]) == 1
    assert order["items"][0]["qty"] == 2
    assert float(order["grand_total"]) == 300.00


@pytest.mark.asyncio
async def test_get_order_with_line_items(client: AsyncClient, seed_user):
    store = await _seed_store_and_user(seed_user)
    sku = await _seed_sku(store.id)

    # Create an order first
    payload = {
        "store_id": str(store.id),
        "payment_method": "cash",
        "source": "manual",
        "items": [
            {
                "sku_id": str(sku.id),
                "qty": 1,
                "unit_price": 99.00,
                "discount": 0,
                "line_total": 99.00,
            }
        ],
    }
    create_resp = await client.post(f"/api/stores/{store.id}/orders", json=payload)
    assert create_resp.status_code == 201
    order_id = create_resp.json()["data"]["id"]

    # Get the order
    resp = await client.get(f"/api/stores/{store.id}/orders/{order_id}")
    assert resp.status_code == 200
    order = resp.json()["data"]
    assert order["id"] == order_id
    assert len(order["items"]) == 1


@pytest.mark.asyncio
async def test_list_orders_with_filters(client: AsyncClient, seed_user):
    store = await _seed_store_and_user(seed_user)
    sku = await _seed_sku(store.id)

    # Create two orders with different payment methods
    for pm in ["cash", "nets"]:
        payload = {
            "store_id": str(store.id),
            "payment_method": pm,
            "source": "manual",
            "items": [
                {
                    "sku_id": str(sku.id),
                    "qty": 1,
                    "unit_price": 50.00,
                    "discount": 0,
                    "line_total": 50.00,
                }
            ],
        }
        resp = await client.post(f"/api/stores/{store.id}/orders", json=payload)
        assert resp.status_code == 201

    # List all
    resp = await client.get(f"/api/stores/{store.id}/orders")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2

    # Filter by payment method
    resp = await client.get(f"/api/stores/{store.id}/orders?payment_method=cash")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    # Filter by source
    resp = await client.get(f"/api/stores/{store.id}/orders?source=manual")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2

    # Filter by status
    resp = await client.get(f"/api/stores/{store.id}/orders?status=open")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


@pytest.mark.asyncio
async def test_update_order_status_void(client: AsyncClient, seed_user):
    store = await _seed_store_and_user(seed_user)
    sku = await _seed_sku(store.id)

    payload = {
        "store_id": str(store.id),
        "payment_method": "cash",
        "source": "manual",
        "items": [
            {
                "sku_id": str(sku.id),
                "qty": 1,
                "unit_price": 100.00,
                "discount": 0,
                "line_total": 100.00,
            }
        ],
    }
    create_resp = await client.post(f"/api/stores/{store.id}/orders", json=payload)
    order_id = create_resp.json()["data"]["id"]

    # Void the order
    resp = await client.patch(
        f"/api/stores/{store.id}/orders/{order_id}",
        json={"status": "voided"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "voided"


# ─── Test NEC XML Import ────────────────────────────────────────────


SAMPLE_NEC_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<SalesExport>
  <Transaction>
    <TransactionId>TXN001</TransactionId>
    <Timestamp>2026-05-01T14:30:00</Timestamp>
    <StoreId>{store_name}</StoreId>
    <CashierId>STAFF001</CashierId>
    <PaymentMethod>NETS</PaymentMethod>
    <PaymentRef>REF123</PaymentRef>
    <Items>
      <Item>
        <SKUCode>VE-JWL-001</SKUCode>
        <Quantity>1</Quantity>
        <UnitPrice>299.00</UnitPrice>
        <Discount>0.00</Discount>
        <LineTotal>299.00</LineTotal>
      </Item>
    </Items>
    <Subtotal>299.00</Subtotal>
    <DiscountTotal>0.00</DiscountTotal>
    <TaxTotal>0.00</TaxTotal>
    <GrandTotal>299.00</GrandTotal>
  </Transaction>
  <Transaction>
    <TransactionId>TXN002</TransactionId>
    <Timestamp>2026-05-01T15:00:00</Timestamp>
    <StoreId>{store_name}</StoreId>
    <CashierId>STAFF001</CashierId>
    <PaymentMethod>cash</PaymentMethod>
    <PaymentRef></PaymentRef>
    <Items>
      <Item>
        <SKUCode>VE-JWL-001</SKUCode>
        <Quantity>2</Quantity>
        <UnitPrice>299.00</UnitPrice>
        <Discount>10.00</Discount>
        <LineTotal>588.00</LineTotal>
      </Item>
    </Items>
    <Subtotal>598.00</Subtotal>
    <DiscountTotal>10.00</DiscountTotal>
    <TaxTotal>0.00</TaxTotal>
    <GrandTotal>588.00</GrandTotal>
  </Transaction>
</SalesExport>
"""


@pytest.mark.asyncio
async def test_nec_xml_import(client: AsyncClient, seed_user):
    store = await _seed_store_and_user(seed_user)
    sku = await _seed_sku(store.id)

    xml_content = SAMPLE_NEC_XML.format(store_name=store.name)

    # First import
    resp = await client.post(
        "/api/import/nec-sales",
        files={"file": ("sales.xml", xml_content.encode(), "application/xml")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["imported"] == 2
    assert data["skipped"] == 0

    # Second import of same file should skip all (idempotency)
    resp = await client.post(
        "/api/import/nec-sales",
        files={"file": ("sales.xml", xml_content.encode(), "application/xml")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 0
    assert data["skipped"] == 2


@pytest.mark.asyncio
async def test_nec_xml_import_invalid_xml(client: AsyncClient, seed_user):
    resp = await client.post(
        "/api/import/nec-sales",
        files={"file": ("bad.xml", b"<not valid xml", "application/xml")},
    )
    assert resp.status_code == 400


# ─── Test Sales Summary ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_daily_sales_summary(client: AsyncClient, seed_user):
    store = await _seed_store_and_user(seed_user)
    sku = await _seed_sku(store.id)

    # Create orders for today
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for amount in [100.00, 200.00, 150.00]:
        payload = {
            "store_id": str(store.id),
            "payment_method": "nets",
            "source": "manual",
            "order_date": today,
            "items": [
                {
                    "sku_id": str(sku.id),
                    "qty": 1,
                    "unit_price": amount,
                    "discount": 0,
                    "line_total": amount,
                }
            ],
        }
        resp = await client.post(f"/api/stores/{store.id}/orders", json=payload)
        assert resp.status_code == 201

    # Get daily summary
    resp = await client.get(f"/api/stores/{store.id}/sales/daily?date={today_date}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["order_count"] == 3
    assert data["total_sales"] == 450.00
    assert data["avg_order_value"] == 150.00
    assert len(data["by_payment_method"]) == 1
    assert data["by_payment_method"][0]["payment_method"] == "nets"


@pytest.mark.asyncio
async def test_sales_summary_date_range(client: AsyncClient, seed_user):
    store = await _seed_store_and_user(seed_user)
    sku = await _seed_sku(store.id)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    payload = {
        "store_id": str(store.id),
        "payment_method": "cash",
        "source": "manual",
        "order_date": today,
        "items": [
            {
                "sku_id": str(sku.id),
                "qty": 1,
                "unit_price": 250.00,
                "discount": 0,
                "line_total": 250.00,
            }
        ],
    }
    resp = await client.post(f"/api/stores/{store.id}/orders", json=payload)
    assert resp.status_code == 201

    resp = await client.get(
        f"/api/stores/{store.id}/sales/summary?from={today_date}&to={today_date}"
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total_sales"] == 250.00
    assert data["order_count"] == 1
    assert len(data["daily"]) == 1


@pytest.mark.asyncio
async def test_sales_by_category(client: AsyncClient, seed_user):
    store = await _seed_store_and_user(seed_user)
    category = await _seed_category(store.id)
    sku = await _seed_sku(store.id, category_id=category.id)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    payload = {
        "store_id": str(store.id),
        "payment_method": "nets",
        "source": "manual",
        "order_date": today,
        "items": [
            {
                "sku_id": str(sku.id),
                "qty": 3,
                "unit_price": 100.00,
                "discount": 0,
                "line_total": 300.00,
            }
        ],
    }
    resp = await client.post(f"/api/stores/{store.id}/orders", json=payload)
    assert resp.status_code == 201

    resp = await client.get(
        f"/api/stores/{store.id}/sales/by-category?from={today_date}&to={today_date}"
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) >= 1
    found = [c for c in data if c["category_name"] == "Jewellery"]
    assert len(found) == 1
    assert found[0]["total_sales"] == 300.00
    assert found[0]["qty_sold"] == 3


@pytest.mark.asyncio
async def test_sales_by_brand(client: AsyncClient, seed_user):
    store = await _seed_store_and_user(seed_user)
    brand = await _seed_brand()
    sku = await _seed_sku(store.id, brand_id=brand.id, sku_code="VE-JWL-BR1")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    payload = {
        "store_id": str(store.id),
        "payment_method": "credit_card",
        "source": "manual",
        "order_date": today,
        "items": [
            {
                "sku_id": str(sku.id),
                "qty": 1,
                "unit_price": 599.00,
                "discount": 0,
                "line_total": 599.00,
            }
        ],
    }
    resp = await client.post(f"/api/stores/{store.id}/orders", json=payload)
    assert resp.status_code == 201

    resp = await client.get(
        f"/api/stores/{store.id}/sales/by-brand?from={today_date}&to={today_date}"
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) >= 1
    found = [b for b in data if b["brand_name"] == "Victoria Enso"]
    assert len(found) == 1
    assert found[0]["total_sales"] == 599.00


@pytest.mark.asyncio
async def test_nec_xml_import_oversized_file(client: AsyncClient, seed_user):
    """File exceeding 10MB limit should be rejected."""
    large_content = b"<SalesExport>" + (b"x" * (10 * 1024 * 1024 + 1)) + b"</SalesExport>"
    resp = await client.post(
        "/api/import/nec-sales",
        files={"file": ("big.xml", large_content, "application/xml")},
    )
    assert resp.status_code == 413
    assert "10MB" in resp.json()["detail"]


# ─── Test Salesperson Aliases CRUD ─────────────────────────────────


@pytest.mark.asyncio
async def test_salesperson_alias_crud(client: AsyncClient, seed_user):
    """Create, list, and delete salesperson aliases."""
    store = await _seed_store_and_user(seed_user)

    # Create alias
    resp = await client.post(
        f"/api/stores/{store.id}/sales/salesperson-aliases",
        json={"alias_name": "Johnny", "user_id": str(seed_user.id)},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["success"] is True
    alias = data["data"]
    assert alias["alias_name"] == "Johnny"
    assert alias["user_id"] == str(seed_user.id)
    assert alias["store_id"] == str(store.id)
    alias_id = alias["id"]

    # List aliases
    resp = await client.get(
        f"/api/stores/{store.id}/sales/salesperson-aliases"
    )
    assert resp.status_code == 200
    aliases = resp.json()["data"]
    assert len(aliases) == 1
    assert aliases[0]["alias_name"] == "Johnny"

    # Delete alias
    resp = await client.delete(
        f"/api/stores/{store.id}/sales/salesperson-aliases/{alias_id}"
    )
    assert resp.status_code == 204

    # Verify deleted
    resp = await client.get(
        f"/api/stores/{store.id}/sales/salesperson-aliases"
    )
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 0


@pytest.mark.asyncio
async def test_delete_nonexistent_alias_returns_404(client: AsyncClient, seed_user):
    store = await _seed_store_and_user(seed_user)
    fake_id = str(uuid.uuid4())
    resp = await client.delete(
        f"/api/stores/{store.id}/sales/salesperson-aliases/{fake_id}"
    )
    assert resp.status_code == 404


# ─── Test Sales by Staff ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_sales_by_staff(client: AsyncClient, seed_user):
    """Sales grouped by salesperson_id with totals."""
    store = await _seed_store_and_user(seed_user)
    sku = await _seed_sku(store.id)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Create orders with salesperson_id set
    for amount in [100.00, 200.00]:
        payload = {
            "store_id": str(store.id),
            "payment_method": "nets",
            "source": "manual",
            "order_date": today,
            "items": [
                {
                    "sku_id": str(sku.id),
                    "qty": 1,
                    "unit_price": amount,
                    "discount": 0,
                    "line_total": amount,
                }
            ],
        }
        resp = await client.post(f"/api/stores/{store.id}/orders", json=payload)
        assert resp.status_code == 201

    # Assign salesperson_id directly via DB for the test
    async with TestSessionLocal() as session:
        from sqlalchemy import update
        await session.execute(
            update(Order)
            .where(Order.store_id == store.id)
            .values(salesperson_id=seed_user.id)
        )
        await session.commit()

    resp = await client.get(
        f"/api/stores/{store.id}/sales/by-staff?from={today_date}&to={today_date}"
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True
    summaries = data["data"]
    assert len(summaries) >= 1

    # Find the entry for our salesperson
    sp_entry = [s for s in summaries if s["salesperson_id"] == str(seed_user.id)]
    assert len(sp_entry) == 1
    assert sp_entry[0]["order_count"] == 2
    assert sp_entry[0]["total_sales"] == 300.00
    assert sp_entry[0]["avg_order_value"] == 150.00
    assert sp_entry[0]["salesperson_name"] == "Test User"


@pytest.mark.asyncio
async def test_sales_by_staff_empty(client: AsyncClient, seed_user):
    """By-staff endpoint returns empty list when no orders exist."""
    store = await _seed_store_and_user(seed_user)
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    resp = await client.get(
        f"/api/stores/{store.id}/sales/by-staff?from={today_date}&to={today_date}"
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == []
