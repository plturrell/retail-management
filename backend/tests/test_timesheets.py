from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import TestSessionLocal
from app.models.store import Store
from app.models.user import User, UserStoreRole, RoleEnum
from app.models.timesheet import TimeEntry, TimeEntryStatus


@pytest_asyncio.fixture
async def seed_store_and_user():
    """Create a store and user with manager role for timesheet tests."""
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
        await session.refresh(user)

        # Give user manager role so they can access store-scoped endpoints
        role = UserStoreRole(
            user_id=user.id,
            store_id=store.id,
            role=RoleEnum.manager,
        )
        session.add(role)
        await session.commit()
        await session.refresh(store)
        await session.refresh(user)
        return store, user


class TestClockIn:
    @pytest.mark.asyncio
    async def test_clock_in(self, client: AsyncClient, seed_store_and_user):
        store, user = seed_store_and_user
        resp = await client.post(
            "/api/timesheets/clock-in",
            json={"store_id": str(store.id), "notes": "Starting shift"},
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["user_id"] == str(user.id)
        assert data["store_id"] == str(store.id)
        assert data["clock_out"] is None
        assert data["status"] == "pending"
        assert data["notes"] == "Starting shift"

        # Verify status endpoint shows clocked in
        status_resp = await client.get("/api/timesheets/status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()["data"]
        assert status_data is not None
        assert status_data["id"] == data["id"]

    @pytest.mark.asyncio
    async def test_double_clock_in(self, client: AsyncClient, seed_store_and_user):
        store, _ = seed_store_and_user
        # First clock in
        resp1 = await client.post(
            "/api/timesheets/clock-in",
            json={"store_id": str(store.id)},
        )
        assert resp1.status_code == 201

        # Second clock in should fail
        resp2 = await client.post(
            "/api/timesheets/clock-in",
            json={"store_id": str(store.id)},
        )
        assert resp2.status_code == 400
        assert "Already clocked in" in resp2.json()["detail"]


class TestClockOut:
    @pytest.mark.asyncio
    async def test_clock_out(self, client: AsyncClient, seed_store_and_user):
        store, _ = seed_store_and_user
        # Clock in first
        await client.post(
            "/api/timesheets/clock-in",
            json={"store_id": str(store.id)},
        )

        # Clock out
        resp = await client.post(
            "/api/timesheets/clock-out",
            json={"break_minutes": 30, "notes": "End of shift"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["clock_out"] is not None
        assert data["break_minutes"] == 30
        assert data["hours_worked"] is not None
        # hours_worked should be >= 0
        assert data["hours_worked"] >= 0

    @pytest.mark.asyncio
    async def test_clock_out_without_clock_in(self, client: AsyncClient, seed_store_and_user):
        # Don't clock in, just try to clock out
        resp = await client.post(
            "/api/timesheets/clock-out",
            json={},
        )
        assert resp.status_code == 400
        assert "Not currently clocked in" in resp.json()["detail"]


class TestListTimesheets:
    @pytest.mark.asyncio
    async def test_list_timesheets(self, client: AsyncClient, seed_store_and_user):
        store, user = seed_store_and_user

        # Create some time entries directly in DB
        now = datetime.now(timezone.utc)
        async with TestSessionLocal() as session:
            entry1 = TimeEntry(
                user_id=user.id,
                store_id=store.id,
                clock_in=now - timedelta(hours=10),
                clock_out=now - timedelta(hours=2),
                break_minutes=30,
                status=TimeEntryStatus.pending,
            )
            entry2 = TimeEntry(
                user_id=user.id,
                store_id=store.id,
                clock_in=now - timedelta(days=2, hours=10),
                clock_out=now - timedelta(days=2, hours=2),
                break_minutes=0,
                status=TimeEntryStatus.pending,
            )
            session.add_all([entry1, entry2])
            await session.commit()

        # List all
        resp = await client.get(f"/api/stores/{store.id}/timesheets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

        # Filter by date_from (only recent entry)
        date_from = (now - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%S")
        resp2 = await client.get(
            f"/api/stores/{store.id}/timesheets?date_from={date_from}"
        )
        assert resp2.status_code == 200
        assert resp2.json()["total"] == 1


class TestApproveTimesheet:
    @pytest.mark.asyncio
    async def test_approve_timesheet(self, client: AsyncClient, seed_store_and_user):
        store, user = seed_store_and_user

        now = datetime.now(timezone.utc)
        async with TestSessionLocal() as session:
            entry = TimeEntry(
                user_id=user.id,
                store_id=store.id,
                clock_in=now - timedelta(hours=8),
                clock_out=now,
                break_minutes=30,
                status=TimeEntryStatus.pending,
            )
            session.add(entry)
            await session.commit()
            await session.refresh(entry)
            entry_id = entry.id

        resp = await client.patch(
            f"/api/stores/{store.id}/timesheets/{entry_id}",
            json={"status": "approved"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["status"] == "approved"
        assert data["approved_by"] == str(user.id)
