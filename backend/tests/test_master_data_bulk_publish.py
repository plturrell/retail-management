"""Tests for ``POST /api/master-data/products/publish_prices_bulk``.

We mock ``_do_publish_price`` so the test focuses on the bulk endpoint's
contract: the owner+allowlist gate, per-item dispatch, and the per-item
error envelope (so a single 409 doesn't abort the batch).
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routers import master_data


@pytest_asyncio.fixture
async def bulk_client(monkeypatch):
    """Override the publish-price owner gate so the test focuses on the
    bulk-endpoint logic, not the named-publisher allowlist (covered
    elsewhere in test_master_data_publish_gating.py)."""
    actor = {
        "id": "test-user-id",
        "email": "craig@victoriaenso.com",
        "store_roles": [{"role": "owner", "store_id": "JEWEL-01"}],
    }
    app.dependency_overrides[master_data.require_publish_price_owner] = lambda: actor

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.pop(master_data.require_publish_price_owner, None)


@pytest.mark.asyncio
async def test_bulk_publish_succeeds_for_all_items(bulk_client, monkeypatch):
    calls: list[str] = []

    def _fake(sku, req, *, actor, request):
        calls.append(sku)
        return {
            "ok": True,
            "sku": sku,
            "price_id": f"price-{sku}",
            "superseded_price_ids": [],
        }

    monkeypatch.setattr(master_data, "_do_publish_price", _fake)

    resp = await bulk_client.post(
        "/api/master-data/products/publish_prices_bulk",
        json={
            "items": [
                {"sku": "SKU-A", "retail_price": 12.5},
                {"sku": "SKU-B", "retail_price": 30.0, "tax_code": "E"},
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["succeeded"] == 2
    assert body["failed"] == 0
    assert [r["sku"] for r in body["results"]] == ["SKU-A", "SKU-B"]
    assert all(r["ok"] for r in body["results"])
    assert calls == ["SKU-A", "SKU-B"]


@pytest.mark.asyncio
async def test_bulk_publish_continues_after_per_item_failure(bulk_client, monkeypatch):
    """A 409 on item 1 must not abort items 2 and 3 — the batch must
    return ok=false with one failed entry and two succeeded."""

    def _fake(sku, req, *, actor, request):
        if sku == "SKU-CONFLICT":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "price_changed",
                    "message": "stale expected_active_price_id",
                    "expected": "old-id",
                    "actual": "new-id",
                },
            )
        return {
            "ok": True,
            "sku": sku,
            "price_id": f"price-{sku}",
            "superseded_price_ids": ["prev-1"],
        }

    monkeypatch.setattr(master_data, "_do_publish_price", _fake)

    resp = await bulk_client.post(
        "/api/master-data/products/publish_prices_bulk",
        json={
            "items": [
                {"sku": "SKU-OK1", "retail_price": 10.0},
                {"sku": "SKU-CONFLICT", "retail_price": 20.0, "expected_active_price_id": "old-id"},
                {"sku": "SKU-OK2", "retail_price": 30.0},
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["succeeded"] == 2
    assert body["failed"] == 1
    by_sku = {r["sku"]: r for r in body["results"]}
    assert by_sku["SKU-OK1"]["ok"] is True
    assert by_sku["SKU-OK2"]["ok"] is True
    fail = by_sku["SKU-CONFLICT"]
    assert fail["ok"] is False
    assert fail["error"]["status_code"] == 409
    assert fail["error"]["code"] == "price_changed"


@pytest.mark.asyncio
async def test_bulk_publish_rejects_empty_items(bulk_client):
    resp = await bulk_client.post(
        "/api/master-data/products/publish_prices_bulk",
        json={"items": []},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_bulk_publish_caps_at_500_items(bulk_client):
    items = [{"sku": f"SKU-{i}", "retail_price": 1.0} for i in range(501)]
    resp = await bulk_client.post(
        "/api/master-data/products/publish_prices_bulk",
        json={"items": items},
    )
    assert resp.status_code == 422
