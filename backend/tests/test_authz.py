from datetime import time

import pytest
from httpx import AsyncClient

from app.models.store import Store
from app.models.user import RoleEnum, User, UserStoreRole
from tests.conftest import TestSessionLocal


async def _create_store(name: str) -> Store:
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


async def _create_user(firebase_uid: str, email: str) -> User:
    async with TestSessionLocal() as session:
        user = User(
            firebase_uid=firebase_uid,
            email=email,
            full_name=email.split("@")[0].title(),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _assign_role(user_id, store_id, role: RoleEnum) -> None:
    async with TestSessionLocal() as session:
        assignment = UserStoreRole(
            user_id=user_id,
            store_id=store_id,
            role=role,
        )
        session.add(assignment)
        await session.commit()


@pytest.mark.asyncio
async def test_create_user_requires_matching_token_uid(
    client: AsyncClient,
    auth_claims,
):
    auth_claims["uid"] = "caller-uid"
    auth_claims["email"] = "caller@example.com"

    resp = await client.post(
        "/api/users",
        json={
            "firebase_uid": "different-uid",
            "email": "new-user@example.com",
            "full_name": "New User",
        },
    )
    assert resp.status_code == 403
    assert "own user record" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_user_allows_self_bootstrap(
    client: AsyncClient,
    auth_claims,
):
    auth_claims["uid"] = "bootstrap-uid"
    auth_claims["email"] = "bootstrap@example.com"

    resp = await client.post(
        "/api/users",
        json={
            "firebase_uid": "bootstrap-uid",
            "email": "bootstrap@example.com",
            "full_name": "Bootstrap User",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["firebase_uid"] == "bootstrap-uid"


@pytest.mark.asyncio
async def test_store_scoped_orders_reject_cross_store_access(
    client: AsyncClient,
    seed_user,
):
    store_a = await _create_store("Store A")
    store_b = await _create_store("Store B")
    await _assign_role(seed_user.id, store_a.id, RoleEnum.owner)

    resp = await client.get(f"/api/stores/{store_b.id}/orders")
    assert resp.status_code == 403
    assert "access to this store" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_assign_store_role_requires_owner(
    client: AsyncClient,
    seed_user,
):
    store = await _create_store("Role Store")
    await _assign_role(seed_user.id, store.id, RoleEnum.staff)
    other_user = await _create_user("other-user-uid", "other@example.com")

    resp = await client.post(
        "/api/users/roles",
        json={
            "user_id": str(other_user.id),
            "store_id": str(store.id),
            "role": "manager",
        },
    )
    assert resp.status_code == 403
    assert "Requires at least owner role" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_analytics_requires_store_access(
    client: AsyncClient,
    seed_user,
):
    store = await _create_store("Analytics Store")
    # seed_user has NO role for this store
    resp = await client.get(
        f"/api/stores/{store.id}/analytics/margins?from=2026-01-01&to=2026-12-31"
    )
    assert resp.status_code == 403
    assert "access to this store" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_pricing_requires_store_access(
    client: AsyncClient,
    seed_user,
):
    store = await _create_store("Pricing Store")
    # seed_user has NO role for this store
    resp = await client.post(
        f"/api/stores/{store.id}/strategy/dynamic_pricing",
        json={
            "current_discount": 10,
            "cogs_sgd": 100,
            "target_margin": 50,
            "sales_velocity": "moderate",
        },
    )
    assert resp.status_code == 403
    assert "access to this store" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_staff_cannot_access_manager_only_endpoints(
    client: AsyncClient,
    seed_user,
):
    store = await _create_store("Staff Store")
    await _assign_role(seed_user.id, store.id, RoleEnum.staff)
    resp = await client.get(f"/api/stores/{store.id}/payroll/employees")
    assert resp.status_code == 403
    assert "Requires at least manager role" in resp.json()["detail"]
