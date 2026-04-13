"""Tests for user profile management, staff management, and role lifecycle."""
from __future__ import annotations

from datetime import time
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.models.store import Store
from app.models.user import RoleEnum, User, UserStoreRole
from tests.conftest import TestSessionLocal


# ── helpers ──────────────────────────────────────────────────────────────────


async def _create_store(name: str = "Test Store") -> Store:
    async with TestSessionLocal() as session:
        store = Store(
            name=name,
            location="Singapore",
            address=f"{name} address",
            business_hours_start=time(10, 0),
            business_hours_end=time(22, 0),
        )
        session.add(store)
        await session.commit()
        await session.refresh(store)
        return store


async def _create_user(firebase_uid: str, email: str, full_name: str | None = None) -> User:
    async with TestSessionLocal() as session:
        user = User(
            firebase_uid=firebase_uid,
            email=email,
            full_name=full_name or email.split("@")[0].title(),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _assign_role(user_id, store_id, role: RoleEnum) -> UserStoreRole:
    async with TestSessionLocal() as session:
        assignment = UserStoreRole(user_id=user_id, store_id=store_id, role=role)
        session.add(assignment)
        await session.commit()
        await session.refresh(assignment)
        return assignment


# ── GET /api/users/me ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_me_returns_profile(client: AsyncClient, seed_user):
    resp = await client.get("/api/users/me")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["email"] == "test@example.com"
    assert data["full_name"] == "Test User"
    assert data["firebase_uid"] == "test-firebase-uid"


@pytest.mark.asyncio
async def test_get_me_includes_store_roles(client: AsyncClient, seed_user):
    store = await _create_store()
    await _assign_role(seed_user.id, store.id, RoleEnum.manager)

    resp = await client.get("/api/users/me")
    assert resp.status_code == 200
    roles = resp.json()["data"]["store_roles"]
    assert len(roles) == 1
    assert roles[0]["role"] == "manager"


# ── PATCH /api/users/me ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_me_full_name(client: AsyncClient, seed_user):
    resp = await client.patch("/api/users/me", json={"full_name": "Updated Name"})
    assert resp.status_code == 200
    assert resp.json()["data"]["full_name"] == "Updated Name"


@pytest.mark.asyncio
async def test_update_me_phone(client: AsyncClient, seed_user):
    resp = await client.patch("/api/users/me", json={"phone": "+6591234567"})
    assert resp.status_code == 200
    assert resp.json()["data"]["phone"] == "+6591234567"


@pytest.mark.asyncio
async def test_update_me_ignores_unknown_fields(client: AsyncClient, seed_user):
    resp = await client.patch("/api/users/me", json={"full_name": "Ok", "email": "hack@evil.com"})
    assert resp.status_code == 200
    assert resp.json()["data"]["email"] == "test@example.com"


# ── GET /api/users/stores/{store_id}/employees ───────────────────────────────


@pytest.mark.asyncio
async def test_list_employees_requires_manager(client: AsyncClient, seed_user):
    store = await _create_store()
    await _assign_role(seed_user.id, store.id, RoleEnum.staff)

    resp = await client.get(f"/api/users/stores/{store.id}/employees")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_employees_as_manager(client: AsyncClient, seed_user):
    store = await _create_store()
    await _assign_role(seed_user.id, store.id, RoleEnum.manager)

    resp = await client.get(f"/api/users/stores/{store.id}/employees")
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1
    emp = resp.json()["data"][0]
    assert emp["full_name"] == "Test User"
    assert "role_id" in emp


# ── POST /api/users/roles ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assign_role_requires_owner(client: AsyncClient, seed_user):
    store = await _create_store()
    await _assign_role(seed_user.id, store.id, RoleEnum.manager)
    target = await _create_user("target-uid", "target@example.com")

    resp = await client.post("/api/users/roles", json={
        "user_id": str(target.id),
        "store_id": str(store.id),
        "role": "staff",
    })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_assign_role_success(client: AsyncClient, seed_user):
    store = await _create_store()
    await _assign_role(seed_user.id, store.id, RoleEnum.owner)
    target = await _create_user("target-uid", "target@example.com")

    resp = await client.post("/api/users/roles", json={
        "user_id": str(target.id),
        "store_id": str(store.id),
        "role": "staff",
    })
    assert resp.status_code == 201
    assert resp.json()["data"]["role"] == "staff"


@pytest.mark.asyncio
async def test_assign_duplicate_role_rejected(client: AsyncClient, seed_user):
    store = await _create_store()
    await _assign_role(seed_user.id, store.id, RoleEnum.owner)
    target = await _create_user("target-uid", "target@example.com")
    await _assign_role(target.id, store.id, RoleEnum.staff)

    resp = await client.post("/api/users/roles", json={
        "user_id": str(target.id),
        "store_id": str(store.id),
        "role": "manager",
    })
    assert resp.status_code == 409


# ── PATCH /api/users/roles/{role_id} ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_role_success(client: AsyncClient, seed_user):
    store = await _create_store()
    await _assign_role(seed_user.id, store.id, RoleEnum.owner)
    target = await _create_user("target-uid", "target@example.com")
    role = await _assign_role(target.id, store.id, RoleEnum.staff)

    resp = await client.patch(f"/api/users/roles/{role.id}", json={"role": "manager"})
    assert resp.status_code == 200
    assert resp.json()["data"]["role"] == "manager"


@pytest.mark.asyncio
async def test_update_role_invalid_value(client: AsyncClient, seed_user):
    store = await _create_store()
    await _assign_role(seed_user.id, store.id, RoleEnum.owner)
    target = await _create_user("target-uid", "target@example.com")
    role = await _assign_role(target.id, store.id, RoleEnum.staff)

    resp = await client.patch(f"/api/users/roles/{role.id}", json={"role": "superadmin"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_update_role_not_found(client: AsyncClient, seed_user):
    resp = await client.patch(f"/api/users/roles/{uuid4()}", json={"role": "manager"})
    assert resp.status_code == 404


# ── DELETE /api/users/roles/{role_id} ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_remove_role_success(client: AsyncClient, seed_user):
    store = await _create_store()
    await _assign_role(seed_user.id, store.id, RoleEnum.owner)
    target = await _create_user("target-uid", "target@example.com")
    role = await _assign_role(target.id, store.id, RoleEnum.staff)

    resp = await client.delete(f"/api/users/roles/{role.id}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_remove_own_role_rejected(client: AsyncClient, seed_user):
    store = await _create_store()
    role = await _assign_role(seed_user.id, store.id, RoleEnum.owner)

    resp = await client.delete(f"/api/users/roles/{role.id}")
    assert resp.status_code == 400
    assert "own role" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_remove_role_requires_owner(client: AsyncClient, seed_user):
    store = await _create_store()
    await _assign_role(seed_user.id, store.id, RoleEnum.manager)
    target = await _create_user("target-uid", "target@example.com")
    role = await _assign_role(target.id, store.id, RoleEnum.staff)

    resp = await client.delete(f"/api/users/roles/{role.id}")
    assert resp.status_code == 403


# ── GET /api/users/search ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_users_by_email(client: AsyncClient, seed_user):
    await _create_user("other-uid", "alice@shop.com", "Alice")

    resp = await client.get("/api/users/search", params={"email": "alice"})
    assert resp.status_code == 200
    results = resp.json()["data"]
    assert len(results) == 1
    assert results[0]["email"] == "alice@shop.com"


@pytest.mark.asyncio
async def test_search_users_no_results(client: AsyncClient, seed_user):
    resp = await client.get("/api/users/search", params={"email": "nonexistent"})
    assert resp.status_code == 200
    assert resp.json()["data"] == []
