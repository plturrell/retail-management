from __future__ import annotations

from uuid import uuid4

import pytest

from app.auth.dependencies import RoleEnum
from app.routers import stores as stores_router
from app.services.store_identity import (
    canonical_active_location_stores,
    canonical_store_code_for_value,
    canonicalize_store_code_input,
    infer_canonical_store_code_from_document,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("breeze", "BREEZE-01"),
        ("Breeze by East", "BREEZE-01"),
        ("jewel", "JEWEL-01"),
        ("JEWEL-B1-241", "JEWEL-01"),
        ("takashimaya", "TAKA-01"),
        ("taka", "TAKA-01"),
        ("isetan scotts", "ISETAN-01"),
        ("online", "ONLINE-01"),
        ("shopify", "ONLINE-01"),
    ],
)
def test_canonical_store_code_for_value(value: str, expected: str) -> None:
    assert canonical_store_code_for_value(value) == expected


def test_canonicalize_store_code_input_preserves_unknown_codes() -> None:
    assert canonicalize_store_code_input("custom-99") == "CUSTOM-99"
    assert canonicalize_store_code_input("unknown place") == "unknown place"


def test_infer_canonical_store_code_from_document_uses_store_fields() -> None:
    store_doc = {
        "store_code": "JEWEL-01",
        "name": "VictoriaEnso - Jewel Changi",
        "location": "Jewel Changi Airport",
        "address": "78 Airport Blvd",
    }
    assert infer_canonical_store_code_from_document(store_doc) == "JEWEL-01"


def test_infer_canonical_store_code_from_document_supports_online() -> None:
    store_doc = {
        "name": "VictoriaEnso - Online",
        "location": "Website",
    }
    assert infer_canonical_store_code_from_document(store_doc) == "ONLINE-01"


def test_canonical_active_location_stores_returns_five_ordered_locations() -> None:
    stores = [
        {
            "id": "legacy-jewel",
            "store_code": "JEWEL-LEGACY",
            "name": "VictoriaEnso - Jewel Changi",
            "location": "Jewel Changi Airport",
            "is_active": True,
        },
        {
            "id": "jewel",
            "store_code": "JEWEL-01",
            "name": "Jewel B1 241",
            "location": "Jewel Changi Airport",
            "is_active": True,
        },
        {
            "id": "warehouse",
            "store_code": "WAREHOUSE-01",
            "name": "Back office stock room",
            "is_active": True,
        },
        {"id": "online", "store_code": "ONLINE-01", "name": "Shopify", "is_active": True},
        {"id": "taka", "store_code": "TAKA-01", "name": "Taka", "is_active": True},
        {"id": "breeze", "store_code": "BREEZE-01", "name": "Breeze by East", "is_active": True},
        {"id": "isetan", "store_code": "ISETAN-01", "name": "Isetan Scotts", "is_active": True},
    ]

    active_locations = canonical_active_location_stores(stores)

    assert [store["store_code"] for store in active_locations] == [
        "BREEZE-01",
        "JEWEL-01",
        "TAKA-01",
        "ISETAN-01",
        "ONLINE-01",
    ]
    assert [store["name"] for store in active_locations] == [
        "Breeze",
        "Jewel",
        "Takashimaya",
        "Isetan",
        "Online",
    ]
    assert active_locations[1]["id"] == "jewel"
    assert all(store["id"] != "warehouse" for store in active_locations)


@pytest.mark.asyncio
async def test_system_admin_active_locations_are_the_five_canonical_stores(monkeypatch):
    docs = [
        {"id": str(uuid4()), "store_code": "JEWEL-01", "name": "Jewel Changi", "is_active": True},
        {"id": str(uuid4()), "store_code": "BREEZE-01", "name": "Breeze by East", "is_active": True},
        {"id": str(uuid4()), "store_code": "TAKA-01", "name": "Takashimaya", "is_active": True},
        {"id": str(uuid4()), "store_code": "ISETAN-01", "name": "Isetan Scotts", "is_active": True},
        {"id": str(uuid4()), "store_code": "ONLINE-01", "name": "Online", "is_active": True},
    ]
    monkeypatch.setattr(stores_router, "query_collection", lambda *_args, **_kwargs: docs)

    response = await stores_router.list_stores(
        page=1,
        page_size=50,
        active_locations=True,
        user={
            "id": str(uuid4()),
            "store_roles": [
                {
                    "id": str(uuid4()),
                    "store_id": docs[0]["id"],
                    "user_id": str(uuid4()),
                    "role": RoleEnum.system_admin,
                }
            ],
        },
        db=object(),
    )

    assert [store.store_code for store in response.data] == [
        "BREEZE-01",
        "JEWEL-01",
        "TAKA-01",
        "ISETAN-01",
        "ONLINE-01",
    ]
    assert [store.name for store in response.data] == [
        "Breeze",
        "Jewel",
        "Takashimaya",
        "Isetan",
        "Online",
    ]
