import uuid
from datetime import date, time

import pytest
from httpx import AsyncClient

from app.models.store import Store
from app.models.user import UserStoreRole, RoleEnum
from app.models.payroll import EmployeeProfile, NationalityEnum
from tests.conftest import TestSessionLocal


async def _create_store_and_role(user_id):
    """Helper to create a store and assign the user as owner."""
    async with TestSessionLocal() as session:
        store = Store(
            name="Test Store",
            location="Orchard",
            address="1 Orchard Rd",
            business_hours_start=time(9, 0),
            business_hours_end=time(21, 0),
        )
        session.add(store)
        await session.flush()
        role = UserStoreRole(
            user_id=user_id,
            store_id=store.id,
            role=RoleEnum.owner,
        )
        session.add(role)
        await session.commit()
        await session.refresh(store)
        return store


@pytest.mark.asyncio
async def test_create_employee_profile(client: AsyncClient, seed_user):
    payload = {
        "date_of_birth": "1990-06-15",
        "nationality": "citizen",
        "basic_salary": "4500.00",
        "bank_name": "DBS",
        "start_date": "2024-01-01",
    }
    resp = await client.post(
        f"/api/employees/{seed_user.id}/profile", json=payload
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["nationality"] == "citizen"
    assert float(data["data"]["basic_salary"]) == 4500.00

    # Verify we can get the profile
    resp = await client.get(f"/api/employees/{seed_user.id}/profile")
    assert resp.status_code == 200
    assert resp.json()["data"]["bank_name"] == "DBS"


@pytest.mark.asyncio
async def test_create_payroll_run(client: AsyncClient, seed_user):
    store = await _create_store_and_role(seed_user.id)
    payload = {
        "period_start": "2026-03-01",
        "period_end": "2026-03-31",
    }
    resp = await client.post(
        f"/api/stores/{store.id}/payroll", json=payload
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["status"] == "draft"


@pytest.mark.asyncio
async def test_calculate_payroll(client: AsyncClient, seed_user):
    store = await _create_store_and_role(seed_user.id)

    # Create employee profile (age 30 at 2026-03-31 -> born 1995)
    profile_payload = {
        "date_of_birth": "1995-06-15",
        "nationality": "citizen",
        "basic_salary": "5000.00",
        "start_date": "2024-01-01",
    }
    resp = await client.post(
        f"/api/employees/{seed_user.id}/profile", json=profile_payload
    )
    assert resp.status_code == 201

    # Create payroll run
    run_payload = {
        "period_start": "2026-03-01",
        "period_end": "2026-03-31",
    }
    resp = await client.post(
        f"/api/stores/{store.id}/payroll", json=run_payload
    )
    assert resp.status_code == 201
    run_id = resp.json()["data"]["id"]

    # Calculate payroll
    resp = await client.post(
        f"/api/stores/{store.id}/payroll/{run_id}/calculate"
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "calculated"

    # Verify payslip CPF values (age 30, salary 5000)
    # Employee: 5000 * 0.20 = 1000
    # Employer: 5000 * 0.17 = 850
    assert len(data["payslips"]) == 1
    slip = data["payslips"][0]
    assert float(slip["cpf_employee"]) == 1000.0
    assert float(slip["cpf_employer"]) == 850.0
    assert float(slip["gross_pay"]) == 5000.0
    assert float(slip["net_pay"]) == 4000.0  # 5000 - 1000


@pytest.mark.asyncio
async def test_approve_payroll_separation_of_duties(client: AsyncClient, seed_user):
    store = await _create_store_and_role(seed_user.id)

    # Create employee profile
    profile_payload = {
        "date_of_birth": "1990-01-01",
        "nationality": "citizen",
        "basic_salary": "3000.00",
        "start_date": "2024-01-01",
    }
    resp = await client.post(
        f"/api/employees/{seed_user.id}/profile", json=profile_payload
    )
    assert resp.status_code == 201

    # Create and calculate payroll run
    resp = await client.post(
        f"/api/stores/{store.id}/payroll",
        json={"period_start": "2026-04-01", "period_end": "2026-04-30"},
    )
    run_id = resp.json()["data"]["id"]

    resp = await client.post(
        f"/api/stores/{store.id}/payroll/{run_id}/calculate"
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "calculated"

    # Creator cannot approve (separation of duties)
    resp = await client.post(
        f"/api/stores/{store.id}/payroll/{run_id}/approve"
    )
    assert resp.status_code == 400
    assert "separation of duties" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_approve_payroll_separation_of_duties_error_message(
    client: AsyncClient, seed_user
):
    store = await _create_store_and_role(seed_user.id)
    profile_payload = {
        "date_of_birth": "1990-01-01",
        "nationality": "citizen",
        "basic_salary": "3000.00",
        "start_date": "2024-01-01",
    }
    resp = await client.post(
        f"/api/employees/{seed_user.id}/profile", json=profile_payload
    )
    assert resp.status_code == 201

    resp = await client.post(
        f"/api/stores/{store.id}/payroll",
        json={"period_start": "2026-05-01", "period_end": "2026-05-31"},
    )
    run_id = resp.json()["data"]["id"]

    resp = await client.post(
        f"/api/stores/{store.id}/payroll/{run_id}/calculate"
    )
    assert resp.status_code == 200

    resp = await client.post(
        f"/api/stores/{store.id}/payroll/{run_id}/approve"
    )
    assert resp.status_code == 400
    assert (
        resp.json()["detail"]
        == "Payroll run cannot be approved by its creator (separation of duties)"
    )


@pytest.mark.asyncio
async def test_payslip_adjustment_recalculates_totals(client: AsyncClient, seed_user):
    store = await _create_store_and_role(seed_user.id)

    profile_payload = {
        "date_of_birth": "1995-06-15",
        "nationality": "citizen",
        "basic_salary": "5000.00",
        "start_date": "2024-01-01",
    }
    resp = await client.post(
        f"/api/employees/{seed_user.id}/profile", json=profile_payload
    )
    assert resp.status_code == 201

    resp = await client.post(
        f"/api/stores/{store.id}/payroll",
        json={"period_start": "2026-06-01", "period_end": "2026-06-30"},
    )
    assert resp.status_code == 201
    run_id = resp.json()["data"]["id"]

    resp = await client.post(
        f"/api/stores/{store.id}/payroll/{run_id}/calculate"
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    slip = data["payslips"][0]
    slip_id = slip["id"]
    assert float(slip["gross_pay"]) == 5000.0
    assert float(slip["net_pay"]) == 4000.0

    resp = await client.patch(
        f"/api/stores/{store.id}/payroll/{run_id}/payslips/{slip_id}",
        json={"allowances": "200.00"},
    )
    assert resp.status_code == 200
    adj = resp.json()["data"]
    assert float(adj["allowances"]) == 200.0
    assert float(adj["gross_pay"]) == 5200.0
    assert float(adj["net_pay"]) == 4200.0


@pytest.mark.asyncio
async def test_foreigner_no_cpf(client: AsyncClient, seed_user):
    store = await _create_store_and_role(seed_user.id)

    profile_payload = {
        "date_of_birth": "1990-01-01",
        "nationality": "foreigner",
        "basic_salary": "4000.00",
        "start_date": "2024-01-01",
    }
    resp = await client.post(
        f"/api/employees/{seed_user.id}/profile", json=profile_payload
    )
    assert resp.status_code == 201

    resp = await client.post(
        f"/api/stores/{store.id}/payroll",
        json={"period_start": "2026-03-01", "period_end": "2026-03-31"},
    )
    run_id = resp.json()["data"]["id"]

    resp = await client.post(
        f"/api/stores/{store.id}/payroll/{run_id}/calculate"
    )
    assert resp.status_code == 200
    slip = resp.json()["data"]["payslips"][0]
    assert float(slip["cpf_employee"]) == 0.0
    assert float(slip["cpf_employer"]) == 0.0
    assert float(slip["net_pay"]) == 4000.0
