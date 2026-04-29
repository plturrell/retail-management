"""Unit tests for the CSV inventory import endpoint.

Uses the in-memory Firestore stub from `firestore_memory.py` to exercise the
endpoint logic without touching the real Firestore client. Authentication and
store-role guards are overridden so the focus stays on the import behavior.
"""

from __future__ import annotations

import io
from typing import Iterable
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import (
    RoleEnum,
    get_current_user,
    get_token_claims,
    require_store_access,
    require_store_role,
)
from app.main import app
from app.routers import inventory as inventory_router
from app.services import supply_chain as supply_chain_service

from firestore_memory import MemoryFirestore


STORE_ID = uuid4()
USER_ID = uuid4()


def _store_role_override():
    return {"store_id": str(STORE_ID), "role": RoleEnum.manager.value}


def _current_user_override():
    return {
        "id": str(USER_ID),
        "firebase_uid": "test-uid",
        "email": "test@example.com",
        "full_name": "Test User",
        "store_roles": [{"store_id": str(STORE_ID), "role": RoleEnum.manager.value}],
    }


def _claims_override():
    return {"uid": "test-uid", "email": "test@example.com"}


@pytest.fixture()
def memory(monkeypatch: pytest.MonkeyPatch) -> MemoryFirestore:
    store = MemoryFirestore()
    # Wire the in-memory backend into the inventory router and supply-chain
    # service it delegates to for stage adjustments.
    for name in ("create_document", "get_document", "query_collection", "update_document"):
        monkeypatch.setattr(inventory_router, name, getattr(store, name))
    for name in ("create_document", "get_document", "query_collection", "update_document"):
        monkeypatch.setattr(supply_chain_service, name, getattr(store, name))
    return store


@pytest_asyncio.fixture
async def client(memory: MemoryFirestore):
    app.dependency_overrides[get_current_user] = _current_user_override
    app.dependency_overrides[get_token_claims] = _claims_override
    # Bypass per-store role enforcement: any callable returning a dict works.
    app.dependency_overrides[require_store_access] = _store_role_override
    # `require_store_role(RoleEnum.manager)` returns a fresh dependency callable
    # for each invocation; iterate over the registered dependencies and override
    # any that match the manager-required protector.
    overrides_to_clear: list = []
    for route in app.routes:
        for dep in getattr(route, "dependant", None).dependencies if getattr(route, "dependant", None) else []:
            if getattr(dep.call, "__qualname__", "").startswith("require_store_role"):
                app.dependency_overrides[dep.call] = _store_role_override
                overrides_to_clear.append(dep.call)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_token_claims, None)
    app.dependency_overrides.pop(require_store_access, None)
    for dep_call in overrides_to_clear:
        app.dependency_overrides.pop(dep_call, None)


def _seed_sku(memory: MemoryFirestore, sku_code: str) -> str:
    sku_id = str(uuid4())
    memory.seed(
        f"stores/{STORE_ID}/inventory",
        {
            "id": sku_id,
            "store_id": str(STORE_ID),
            "sku_code": sku_code,
            "description": f"Test SKU {sku_code}",
            "inventory_type": "finished",
            "sourcing_strategy": "supplier_premade",
        },
    )
    return sku_id


def _csv(rows: Iterable[Iterable[str]]) -> bytes:
    buf = io.StringIO()
    for row in rows:
        buf.write(",".join(row))
        buf.write("\n")
    return buf.getvalue().encode("utf-8")


@pytest.mark.asyncio
async def test_csv_import_creates_new_records(memory: MemoryFirestore, client: AsyncClient):
    sku_id = _seed_sku(memory, "ABC-001")

    body = _csv([
        ("sku_code", "qty_on_hand", "reorder_level", "reorder_qty"),
        ("ABC-001", "12", "5", "20"),
    ])
    resp = await client.post(
        f"/api/stores/{STORE_ID}/inventory/import-csv",
        files={"file": ("inv.csv", body, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload == {
        "imported": 1,
        "updated": 0,
        "skipped": 0,
        "errors": [],
    }

    inv_records = memory.query_collection(f"stores/{STORE_ID}/stock")
    assert len(inv_records) == 1
    record = inv_records[0]
    assert record["sku_id"] == sku_id
    assert record["qty_on_hand"] == 12
    assert record["reorder_level"] == 5
    assert record["reorder_qty"] == 20
    # NB: the stock row's `source` is owned by the stage-inventory pipeline
    # (`_sync_finished_stock`) and ends up "manual" after the stage adjustment.
    # The "csv_import" provenance is preserved in the TiDB stock_movements
    # ledger and on the stage row's `last_reference_type` field.
    stage_records = memory.query_collection(f"stores/{STORE_ID}/stage_inventory")
    assert len(stage_records) == 1
    assert stage_records[0]["last_reference_type"] == "inventory_csv_create"
    assert stage_records[0]["quantity_on_hand"] == 12


@pytest.mark.asyncio
async def test_csv_import_updates_existing_record(memory: MemoryFirestore, client: AsyncClient):
    sku_id = _seed_sku(memory, "ABC-002")
    existing_id = str(uuid4())
    memory.seed(
        f"stores/{STORE_ID}/stock",
        {
            "id": existing_id,
            "store_id": str(STORE_ID),
            "sku_id": sku_id,
            "qty_on_hand": 4,
            "reorder_level": 2,
            "reorder_qty": 6,
        },
    )

    body = _csv([
        ("sku_code", "qty_on_hand", "reorder_level", "reorder_qty"),
        ("ABC-002", "20", "8", "40"),
    ])
    resp = await client.post(
        f"/api/stores/{STORE_ID}/inventory/import-csv",
        files={"file": ("inv.csv", body, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["imported"] == 0
    assert payload["updated"] == 1
    assert payload["skipped"] == 0

    record = memory.get_document(f"stores/{STORE_ID}/stock", existing_id)
    assert record is not None
    assert record["qty_on_hand"] == 20
    assert record["reorder_level"] == 8
    assert record["reorder_qty"] == 40
    # See note in test_csv_import_creates_new_records: the stock row's `source`
    # is overwritten by the stage pipeline; provenance lives elsewhere.
    stage_records = memory.query_collection(f"stores/{STORE_ID}/stage_inventory")
    assert len(stage_records) == 1
    assert stage_records[0]["last_reference_type"] == "inventory_csv_update"
    assert stage_records[0]["quantity_on_hand"] == 20


@pytest.mark.asyncio
async def test_csv_import_skips_unknown_sku_and_blank_rows(memory: MemoryFirestore, client: AsyncClient):
    _seed_sku(memory, "REAL-001")

    body = _csv([
        ("sku_code", "qty_on_hand"),
        ("REAL-001", "3"),
        ("UNKNOWN-999", "5"),
        ("", "1"),
    ])
    resp = await client.post(
        f"/api/stores/{STORE_ID}/inventory/import-csv",
        files={"file": ("inv.csv", body, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["imported"] == 1
    assert payload["updated"] == 0
    assert payload["skipped"] == 2
    assert any("UNKNOWN-999" in err for err in payload["errors"])
    assert any("missing sku_code" in err for err in payload["errors"])


@pytest.mark.asyncio
async def test_csv_import_rejects_missing_required_column(client: AsyncClient):
    body = _csv([
        ("sku_code",),
        ("ABC-001",),
    ])
    resp = await client.post(
        f"/api/stores/{STORE_ID}/inventory/import-csv",
        files={"file": ("inv.csv", body, "text/csv")},
    )
    assert resp.status_code == 400
    assert "qty_on_hand" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_csv_import_rejects_empty_file(client: AsyncClient):
    resp = await client.post(
        f"/api/stores/{STORE_ID}/inventory/import-csv",
        files={"file": ("inv.csv", b"", "text/csv")},
    )
    assert resp.status_code == 400
