"""Tests for the /api/supplier-review router (live wiring for Vendor Review).

Covers manager-role gating, the 404 paths, and the path-traversal guard on
the new ``/artifacts/{file_path:path}`` endpoint that streams invoice scans.
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.routers import supplier_review
from tests.firestore_payroll_support import override_owner_user


def _seed_supplier_tree(root: Path, supplier_id: str = "CN-001") -> Path:
    """Build a docs/suppliers/<dir>/orders/<n>.json layout under *root*."""
    supplier_dir = root / "hengweicraft"
    orders_dir = supplier_dir / "orders"
    orders_dir.mkdir(parents=True)

    order_doc = {
        "supplier_id": supplier_id,
        "supplier_name": "Hengwei Craft",
        "order_number": "364",
        "order_date": "2026-03-26",
        "currency": "USD",
        "line_items": [{"sku": "X", "qty": 1}],
        "source_artifacts": [
            {"file": "orders/order-364-source.PNG", "kind": "invoice_scan"}
        ],
    }
    (orders_dir / "364.json").write_text(json.dumps(order_doc))
    (orders_dir / "order-364-source.PNG").write_bytes(b"\x89PNG\r\n\x1a\nFAKE")

    # A second order for list-count assertions.
    second = dict(order_doc, order_number="365")
    (orders_dir / "365.json").write_text(json.dumps(second))
    return supplier_dir


@pytest.fixture
def seeded_suppliers(tmp_path, monkeypatch):
    monkeypatch.setattr(supplier_review, "_SUPPLIERS_ROOT", tmp_path)
    return _seed_supplier_tree(tmp_path)


@pytest.mark.asyncio
async def test_artifact_endpoint_requires_manager_role(
    client: AsyncClient, seeded_suppliers
) -> None:
    # Default conftest user has empty store_roles, so the manager dep rejects.
    response = await client.get(
        "/api/supplier-review/CN-001/artifacts/orders/order-364-source.PNG"
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_artifact_endpoint_returns_404_for_unknown_supplier(
    client: AsyncClient, seeded_suppliers
) -> None:
    with override_owner_user(owner_id=uuid4(), store_id=uuid4()):
        response = await client.get(
            "/api/supplier-review/CN-999/artifacts/orders/order-364-source.PNG"
        )
    assert response.status_code == 404
    assert "Unknown supplier" in response.json()["detail"]


@pytest.mark.asyncio
async def test_artifact_endpoint_returns_404_for_missing_file(
    client: AsyncClient, seeded_suppliers
) -> None:
    with override_owner_user(owner_id=uuid4(), store_id=uuid4()):
        response = await client.get(
            "/api/supplier-review/CN-001/artifacts/orders/does-not-exist.PNG"
        )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_artifact_endpoint_blocks_path_traversal(
    seeded_suppliers, tmp_path
) -> None:
    # Drop a sibling file outside the supplier dir that the traversal payload
    # would resolve to if the guard were missing.
    (tmp_path / "secret.txt").write_text("nope")
    # Bypass HTTP-layer URL normalisation (starlette/httpx collapse "../"
    # before the handler sees it) by calling the route function directly so
    # the in-handler ``relative_to`` guard is exercised on a literal payload.
    from fastapi import HTTPException as _HTTPException
    with pytest.raises(_HTTPException) as exc:
        await supplier_review.get_supplier_artifact(
            supplier_id="CN-001",
            file_path="../secret.txt",
            _={},
        )
    assert exc.value.status_code == 400
    assert "escapes supplier directory" in exc.value.detail


@pytest.mark.asyncio
async def test_artifact_endpoint_streams_existing_file(
    client: AsyncClient, seeded_suppliers
) -> None:
    with override_owner_user(owner_id=uuid4(), store_id=uuid4()):
        response = await client.get(
            "/api/supplier-review/CN-001/artifacts/orders/order-364-source.PNG"
        )
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\x89PNG")
    assert response.headers["content-type"].startswith("image/")


@pytest.mark.asyncio
async def test_list_supplier_orders_groups_by_supplier_id(
    client: AsyncClient, seeded_suppliers
) -> None:
    with override_owner_user(owner_id=uuid4(), store_id=uuid4()):
        response = await client.get("/api/supplier-review/CN-001/orders")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["supplier_id"] == "CN-001"
    assert payload["count"] == 2
    order_numbers = sorted(o["order_number"] for o in payload["orders"])
    assert order_numbers == ["364", "365"]


@pytest.mark.asyncio
async def test_get_supplier_order_returns_full_document(
    client: AsyncClient, seeded_suppliers
) -> None:
    with override_owner_user(owner_id=uuid4(), store_id=uuid4()):
        response = await client.get("/api/supplier-review/CN-001/orders/364")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["order_number"] == "364"
    assert body["supplier_id"] == "CN-001"
    assert body["line_items"] == [{"sku": "X", "qty": 1}]


@pytest.mark.asyncio
async def test_get_supplier_order_returns_404_when_missing(
    client: AsyncClient, seeded_suppliers
) -> None:
    with override_owner_user(owner_id=uuid4(), store_id=uuid4()):
        response = await client.get("/api/supplier-review/CN-001/orders/9999")
    assert response.status_code == 404
