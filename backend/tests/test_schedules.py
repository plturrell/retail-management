from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import TestSessionLocal
from app.models.schedule import Schedule, ScheduleStatusEnum, Shift
from app.models.store import Store
from app.models.user import RoleEnum, User, UserStoreRole


@pytest_asyncio.fixture
async def seed_store_and_user():
    """Create a store and user for schedule tests."""
    async with TestSessionLocal() as session:
        store = Store(
            name="Victoria Enso Jewel",
            location="Jewel Changi Airport",
            address="#02-234 Jewel Changi Airport",
            business_hours_start=time(10, 0),
            business_hours_end=time(22, 0),
        )
        session.add(store)
        await session.flush()
        await session.refresh(store)

        user = User(
            firebase_uid="test-firebase-uid",
            email="test@example.com",
            full_name="Test User",
        )
        session.add(user)
        await session.flush()

        role = UserStoreRole(
            user_id=user.id,
            store_id=store.id,
            role=RoleEnum.owner,
        )
        session.add(role)
        await session.commit()
        await session.refresh(store)
        await session.refresh(user)
        return store, user


def _next_monday(from_date: date | None = None) -> date:
    """Return the next Monday on or after the given date."""
    d = from_date or date(2026, 4, 13)  # A known Monday
    return d


class TestScheduleCRUD:
    @pytest.mark.asyncio
    async def test_create_schedule(self, client: AsyncClient, seed_store_and_user):
        store, user = seed_store_and_user
        monday = _next_monday()
        payload = {
            "store_id": str(store.id),
            "week_start": monday.isoformat(),
        }
        resp = await client.post(
            f"/api/stores/{store.id}/schedules", json=payload
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["week_start"] == monday.isoformat()
        assert data["status"] == "draft"
        assert data["created_by"] == str(user.id)

    @pytest.mark.asyncio
    async def test_duplicate_schedule(self, client: AsyncClient, seed_store_and_user):
        store, _ = seed_store_and_user
        monday = _next_monday()
        payload = {
            "store_id": str(store.id),
            "week_start": monday.isoformat(),
        }
        resp1 = await client.post(
            f"/api/stores/{store.id}/schedules", json=payload
        )
        assert resp1.status_code == 201

        resp2 = await client.post(
            f"/api/stores/{store.id}/schedules", json=payload
        )
        assert resp2.status_code == 409
        assert "already exists" in resp2.json()["detail"]

    @pytest.mark.asyncio
    async def test_add_shifts(self, client: AsyncClient, seed_store_and_user):
        store, user = seed_store_and_user
        monday = _next_monday()

        # Create schedule
        sched_resp = await client.post(
            f"/api/stores/{store.id}/schedules",
            json={
                "store_id": str(store.id),
                "week_start": monday.isoformat(),
            },
        )
        assert sched_resp.status_code == 201
        schedule_id = sched_resp.json()["data"]["id"]

        # Add a shift on Monday
        shift_payload = {
            "user_id": str(user.id),
            "shift_date": monday.isoformat(),
            "start_time": "10:00:00",
            "end_time": "18:00:00",
            "break_minutes": 60,
            "notes": "Opening shift",
        }
        shift_resp = await client.post(
            f"/api/stores/{store.id}/schedules/{schedule_id}/shifts",
            json=shift_payload,
        )
        assert shift_resp.status_code == 201
        shift_data = shift_resp.json()["data"]
        assert shift_data["user_id"] == str(user.id)
        assert shift_data["shift_date"] == monday.isoformat()
        assert shift_data["hours"] == 7.0  # 8h - 1h break

        # Add a shift on Tuesday
        tuesday = monday + timedelta(days=1)
        shift_payload2 = {
            "user_id": str(user.id),
            "shift_date": tuesday.isoformat(),
            "start_time": "12:00:00",
            "end_time": "20:00:00",
            "break_minutes": 60,
        }
        shift_resp2 = await client.post(
            f"/api/stores/{store.id}/schedules/{schedule_id}/shifts",
            json=shift_payload2,
        )
        assert shift_resp2.status_code == 201

        # Get schedule — should have 2 shifts
        get_resp = await client.get(
            f"/api/stores/{store.id}/schedules/{schedule_id}"
        )
        assert get_resp.status_code == 200
        sched_data = get_resp.json()["data"]
        assert len(sched_data["schedule"]["shifts"]) == 2

    @pytest.mark.asyncio
    async def test_publish_schedule(self, client: AsyncClient, seed_store_and_user):
        store, _ = seed_store_and_user
        monday = _next_monday()

        sched_resp = await client.post(
            f"/api/stores/{store.id}/schedules",
            json={
                "store_id": str(store.id),
                "week_start": monday.isoformat(),
            },
        )
        schedule_id = sched_resp.json()["data"]["id"]

        # Publish
        patch_resp = await client.patch(
            f"/api/stores/{store.id}/schedules/{schedule_id}",
            json={"status": "published"},
        )
        assert patch_resp.status_code == 200
        data = patch_resp.json()["data"]
        assert data["status"] == "published"
        assert data["published_at"] is not None

    @pytest.mark.asyncio
    async def test_delete_draft_schedule(
        self, client: AsyncClient, seed_store_and_user
    ):
        store, _ = seed_store_and_user
        monday = _next_monday()

        sched_resp = await client.post(
            f"/api/stores/{store.id}/schedules",
            json={
                "store_id": str(store.id),
                "week_start": monday.isoformat(),
            },
        )
        schedule_id = sched_resp.json()["data"]["id"]

        del_resp = await client.delete(
            f"/api/stores/{store.id}/schedules/{schedule_id}"
        )
        assert del_resp.status_code == 204

        # Verify it's gone
        get_resp = await client.get(
            f"/api/stores/{store.id}/schedules/{schedule_id}"
        )
        assert get_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_published_schedule(
        self, client: AsyncClient, seed_store_and_user
    ):
        store, _ = seed_store_and_user
        monday = _next_monday()

        sched_resp = await client.post(
            f"/api/stores/{store.id}/schedules",
            json={
                "store_id": str(store.id),
                "week_start": monday.isoformat(),
            },
        )
        schedule_id = sched_resp.json()["data"]["id"]

        # Publish first
        await client.patch(
            f"/api/stores/{store.id}/schedules/{schedule_id}",
            json={"status": "published"},
        )

        # Try to delete — should fail
        del_resp = await client.delete(
            f"/api/stores/{store.id}/schedules/{schedule_id}"
        )
        assert del_resp.status_code == 400
        assert "published" in del_resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_my_shifts(self, client: AsyncClient, seed_store_and_user):
        store, user = seed_store_and_user
        monday = _next_monday()

        # Create schedule + shift
        sched_resp = await client.post(
            f"/api/stores/{store.id}/schedules",
            json={
                "store_id": str(store.id),
                "week_start": monday.isoformat(),
            },
        )
        schedule_id = sched_resp.json()["data"]["id"]

        shift_payload = {
            "user_id": str(user.id),
            "shift_date": monday.isoformat(),
            "start_time": "10:00:00",
            "end_time": "18:00:00",
            "break_minutes": 60,
        }
        await client.post(
            f"/api/stores/{store.id}/schedules/{schedule_id}/shifts",
            json=shift_payload,
        )

        # Query my shifts
        resp = await client.get(
            f"/api/stores/{store.id}/schedules/my-shifts",
            params={"from": monday.isoformat(), "to": (monday + timedelta(days=6)).isoformat()},
        )
        assert resp.status_code == 200
        shifts = resp.json()["data"]
        assert len(shifts) >= 1
        assert shifts[0]["user_id"] == str(user.id)
