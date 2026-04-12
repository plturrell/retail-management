import uuid

import pytest
from httpx import AsyncClient

from app.models.store import Store
from app.models.user import UserStoreRole, RoleEnum
from tests.conftest import TestSessionLocal


@pytest.mark.asyncio
async def test_create_and_list_stores(client: AsyncClient, seed_user):
    # Create a store
    payload = {
        "name": "Test Store",
        "location": "Test Location",
        "address": "123 Test St",
        "business_hours_start": "09:00:00",
        "business_hours_end": "21:00:00",
        "is_active": True,
    }
    resp = await client.post("/api/stores", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["success"] is True
    store_id = data["data"]["id"]

    # Assign the user to the store so listing works
    async with TestSessionLocal() as session:
        role = UserStoreRole(
            user_id=seed_user.id,
            store_id=uuid.UUID(store_id),
            role=RoleEnum.owner,
        )
        session.add(role)
        await session.commit()

    # List stores
    resp = await client.get("/api/stores")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_get_store_not_found(client: AsyncClient, seed_user):
    resp = await client.get("/api/stores/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
