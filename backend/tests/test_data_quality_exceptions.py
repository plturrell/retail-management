"""Tests for /api/data-quality/exceptions.

This worklist endpoint is the canonical "perfect quality" gate before SKUs
are allowed to reach POS, so the row-shape and the severity/field filters
are part of the staff-portal contract.
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.routers import data_quality
from tests.firestore_payroll_support import override_owner_user


def _seed_master_list(tmp_path, monkeypatch, products: list[dict]) -> None:
    payload = {
        "generated_at": "2026-04-29T00:00:00",
        "products": products,
    }
    path = tmp_path / "master_product_list.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(data_quality, "_MASTER_LIST_PATH", path)


def _good_product(**overrides) -> dict:
    base = {
        "id": str(uuid4()),
        "sku_code": "OK-001",
        "description": "Healthy ring with full data",
        "material": "Rose Quartz",
        "product_type": "Ring",
        "inventory_category": "finished_for_sale",
        "stocking_status": "in_stock",
        "stocking_location": "warehouse",
        "cost_price": 10.0,
        "retail_price": 25.0,
        "qty_on_hand": 5,
        "sale_ready": True,
        "nec_plu": "PLU-1",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_exceptions_returns_404_when_master_list_missing(
    client: AsyncClient, tmp_path, monkeypatch
) -> None:
    missing = tmp_path / "does-not-exist.json"
    monkeypatch.setattr(data_quality, "_MASTER_LIST_PATH", missing)

    with override_owner_user(owner_id=uuid4(), store_id=uuid4()):
        response = await client.get("/api/data-quality/exceptions")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_exceptions_requires_manager_role(client: AsyncClient) -> None:
    # Default conftest user has empty store_roles → manager dep rejects.
    response = await client.get("/api/data-quality/exceptions")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_exceptions_emits_one_row_per_issue_and_skips_clean_products(
    client: AsyncClient, tmp_path, monkeypatch
) -> None:
    products = [
        _good_product(sku_code="OK-001"),
        # Sale-ready item missing retail_price → 1 error row.
        _good_product(
            sku_code="MISS-RETAIL",
            retail_price=None,
            sale_ready=True,
            nec_plu="PLU-2",
        ),
        # Stocked item missing qty_on_hand → 1 error row.
        _good_product(sku_code="MISS-QTY", qty_on_hand=None),
    ]
    _seed_master_list(tmp_path, monkeypatch, products)

    with override_owner_user(owner_id=uuid4(), store_id=uuid4()):
        response = await client.get("/api/data-quality/exceptions")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_products"] == 3
    assert body["affected_sku_count"] == 2
    rows = body["rows"]
    assert len(rows) == body["exception_count"] >= 2
    sku_to_fields = {r["sku_code"]: r["field"] for r in rows}
    assert "MISS-RETAIL" in sku_to_fields
    assert "MISS-QTY" in sku_to_fields
    # The clean SKU is omitted.
    assert "OK-001" not in {r["sku_code"] for r in rows}
    # Errors come before warnings in the sort order.
    severities = [r["severity"] for r in rows]
    assert severities == sorted(severities, key=lambda s: 0 if s == "error" else 1)


@pytest.mark.asyncio
async def test_exceptions_filter_by_severity_returns_only_errors(
    client: AsyncClient, tmp_path, monkeypatch
) -> None:
    products = [
        # warning-only: missing material falls back to "Unknown".
        _good_product(sku_code="WARN-1", material="Unknown"),
        # error: invalid product_type.
        _good_product(sku_code="ERR-1", product_type="Bogus"),
    ]
    _seed_master_list(tmp_path, monkeypatch, products)

    with override_owner_user(owner_id=uuid4(), store_id=uuid4()):
        response = await client.get(
            "/api/data-quality/exceptions", params={"severity": "error"}
        )
    assert response.status_code == 200
    body = response.json()
    assert all(r["severity"] == "error" for r in body["rows"])
    assert any(r["sku_code"] == "ERR-1" for r in body["rows"])
    assert not any(r["sku_code"] == "WARN-1" for r in body["rows"])
    assert body["filters_applied"] == {"severity": "error", "field": None}


@pytest.mark.asyncio
async def test_exceptions_filter_by_field_isolates_one_column(
    client: AsyncClient, tmp_path, monkeypatch
) -> None:
    products = [
        _good_product(sku_code="MISS-RETAIL", retail_price=None, sale_ready=True),
        _good_product(sku_code="MISS-QTY", qty_on_hand=None),
    ]
    _seed_master_list(tmp_path, monkeypatch, products)

    with override_owner_user(owner_id=uuid4(), store_id=uuid4()):
        response = await client.get(
            "/api/data-quality/exceptions", params={"field": "retail_price"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["rows"], "expected at least one retail_price row"
    assert all(r["field"] == "retail_price" for r in body["rows"])
    assert all(r["sku_code"] == "MISS-RETAIL" for r in body["rows"])
    assert body["by_field"] == {"retail_price": len(body["rows"])}
