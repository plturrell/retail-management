from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.firestore import get_firestore_db
from app.routers import skus


def build_client(user_payload: dict) -> TestClient:
    app = FastAPI()
    app.include_router(skus.router)

    async def override_current_user():
        return user_payload

    async def override_firestore_db():
        return object()

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_firestore_db] = override_firestore_db
    return TestClient(app)


def _sku_payload(store_id, sku_id):
    return {
        "id": str(sku_id),
        "store_id": str(store_id),
        "sku_code": "SKU-001",
        "description": "Signature piece",
        "cost_price": 125.0,
        "inventory_type": "finished",
        "sourcing_strategy": "supplier_premade",
        "supplier_name": "GemCo",
        "supplier_sku_code": "GEM-001",
        "internal_code": "INT-001",
    }


def test_sales_promoter_and_sales_manager_get_redacted_sku_fields(monkeypatch):
    store_id = uuid4()
    sku_id = uuid4()

    monkeypatch.setattr(skus, "query_collection", lambda *_args, **_kwargs: [_sku_payload(store_id, sku_id)])
    monkeypatch.setattr(skus, "get_document", lambda *_args, **_kwargs: _sku_payload(store_id, sku_id))

    for role in ("staff", "manager"):
        client = build_client(
            {
                "id": uuid4(),
                "store_roles": [
                    {
                        "id": str(uuid4()),
                        "store_id": store_id,
                        "role": role,
                        "user_id": uuid4(),
                    }
                ],
            }
        )

        list_response = client.get(f"/api/stores/{store_id}/skus")
        detail_response = client.get(f"/api/stores/{store_id}/skus/{sku_id}")
        create_response = client.post(
            f"/api/stores/{store_id}/skus",
            json={
                "store_id": str(store_id),
                "sku_code": "SKU-002",
                "description": "New piece",
                "inventory_type": "finished",
                "sourcing_strategy": "supplier_premade",
            },
        )

        assert list_response.status_code == 200
        assert detail_response.status_code == 200
        list_payload = list_response.json()["data"][0]
        detail_payload = detail_response.json()["data"]
        for payload in (list_payload, detail_payload):
            assert payload["cost_price"] is None
            assert payload["supplier_name"] is None
            assert payload["supplier_sku_code"] is None
            assert payload["internal_code"] is None

        assert create_response.status_code == 403


def test_owner_director_keeps_sensitive_sku_fields_and_owner_sku_crud(monkeypatch):
    store_id = uuid4()
    sku_id = uuid4()

    monkeypatch.setattr(skus, "query_collection", lambda *_args, **_kwargs: [_sku_payload(store_id, sku_id)])
    monkeypatch.setattr(skus, "get_document", lambda *_args, **_kwargs: _sku_payload(store_id, sku_id))
    monkeypatch.setattr(
        skus,
        "create_document",
        lambda _collection, data, doc_id=None: data | {"id": doc_id},
    )

    client = build_client(
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

    list_response = client.get(f"/api/stores/{store_id}/skus")
    create_response = client.post(
        f"/api/stores/{store_id}/skus",
        json={
            "store_id": str(store_id),
            "sku_code": "SKU-002",
            "description": "New piece",
            "inventory_type": "finished",
            "sourcing_strategy": "supplier_premade",
            "supplier_name": "GemCo",
            "cost_price": 180,
        },
    )

    assert list_response.status_code == 200
    payload = list_response.json()["data"][0]
    assert payload["cost_price"] == 125.0
    assert payload["supplier_name"] == "GemCo"
    assert payload["supplier_sku_code"] == "GEM-001"

    assert create_response.status_code == 201
    created_payload = create_response.json()["data"]
    assert created_payload["supplier_name"] == "GemCo"
    assert created_payload["cost_price"] == 180
