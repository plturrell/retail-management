import json
import uuid
from datetime import date, datetime, time, timedelta

import pytest
from httpx import AsyncClient

from app.models.order import Order, OrderStatus, OrderSource
from app.models.payroll import CommissionRule, EmployeeProfile, NationalityEnum
from app.models.store import Store
from app.models.timesheet import TimeEntry, TimeEntryStatus
from app.models.user import UserStoreRole, RoleEnum
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



async def _create_approved_time_entries(user_id, store_id, entries_spec):
    """Create approved TimeEntry records.

    entries_spec: list of (clock_in_dt, clock_out_dt, break_minutes)
    """
    async with TestSessionLocal() as session:
        for clock_in, clock_out, break_min in entries_spec:
            entry = TimeEntry(
                user_id=user_id,
                store_id=store_id,
                clock_in=clock_in,
                clock_out=clock_out,
                break_minutes=break_min,
                status=TimeEntryStatus.approved,
            )
            session.add(entry)
        await session.commit()


@pytest.mark.asyncio
async def test_calculate_payroll_hourly_with_timesheets(client: AsyncClient, seed_user):
    """Hourly-rate employee: gross = hours × rate + overtime at 1.5×."""
    store = await _create_store_and_role(seed_user.id)

    # Create hourly employee: $15/hr
    profile_payload = {
        "date_of_birth": "1995-06-15",
        "nationality": "foreigner",
        "basic_salary": "0.00",
        "hourly_rate": "15.00",
        "start_date": "2024-01-01",
    }
    resp = await client.post(
        f"/api/employees/{seed_user.id}/profile", json=profile_payload
    )
    assert resp.status_code == 201

    # Create payroll run for a single week (Mon-Sun)
    resp = await client.post(
        f"/api/stores/{store.id}/payroll",
        json={"period_start": "2026-03-02", "period_end": "2026-03-08"},
    )
    assert resp.status_code == 201
    run_id = resp.json()["data"]["id"]

    # Create approved time entries: 6 days × 8 hours = 48 hours total
    # Week of 2026-03-02 (Monday) to 2026-03-07 (Saturday)
    entries = []
    for day_offset in range(6):
        clock_in = datetime(2026, 3, 2 + day_offset, 9, 0)
        clock_out = datetime(2026, 3, 2 + day_offset, 17, 30)
        entries.append((clock_in, clock_out, 30))  # 8 hours net each

    await _create_approved_time_entries(seed_user.id, store.id, entries)

    # Calculate payroll
    resp = await client.post(
        f"/api/stores/{store.id}/payroll/{run_id}/calculate"
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "calculated"

    slip = data["payslips"][0]
    # 48 hours total; 44 regular + 4 overtime
    assert float(slip["hours_worked"]) == 48.0
    assert float(slip["overtime_hours"]) == 4.0
    # Regular: 44 × 15 = 660; Overtime: 4 × 15 × 1.5 = 90; Total = 750
    assert float(slip["overtime_pay"]) == 90.0
    assert float(slip["gross_pay"]) == 750.0
    # Foreigner: no CPF
    assert float(slip["cpf_employee"]) == 0.0
    assert float(slip["net_pay"]) == 750.0


@pytest.mark.asyncio
async def test_calculate_payroll_salaried_with_timesheets(client: AsyncClient, seed_user):
    """Salaried employee: uses basic_salary, hours_worked populated for records."""
    store = await _create_store_and_role(seed_user.id)

    # Create salaried employee (no hourly_rate)
    profile_payload = {
        "date_of_birth": "1995-06-15",
        "nationality": "foreigner",
        "basic_salary": "5000.00",
        "start_date": "2024-01-01",
    }
    resp = await client.post(
        f"/api/employees/{seed_user.id}/profile", json=profile_payload
    )
    assert resp.status_code == 201

    # Create payroll run
    resp = await client.post(
        f"/api/stores/{store.id}/payroll",
        json={"period_start": "2026-03-02", "period_end": "2026-03-08"},
    )
    assert resp.status_code == 201
    run_id = resp.json()["data"]["id"]

    # Create approved time entries: 5 days × 8 hours = 40 hours
    entries = []
    for day_offset in range(5):
        clock_in = datetime(2026, 3, 2 + day_offset, 9, 0)
        clock_out = datetime(2026, 3, 2 + day_offset, 17, 30)
        entries.append((clock_in, clock_out, 30))

    await _create_approved_time_entries(seed_user.id, store.id, entries)

    resp = await client.post(
        f"/api/stores/{store.id}/payroll/{run_id}/calculate"
    )
    assert resp.status_code == 200
    slip = resp.json()["data"]["payslips"][0]

    # Hours tracked but gross uses basic_salary
    assert float(slip["hours_worked"]) == 40.0
    assert float(slip["overtime_hours"]) == 0.0
    assert float(slip["overtime_pay"]) == 0.0
    assert float(slip["gross_pay"]) == 5000.0
    assert float(slip["net_pay"]) == 5000.0


@pytest.mark.asyncio
async def test_calculate_payroll_no_timesheets(client: AsyncClient, seed_user):
    """When no approved timesheets exist, hours_worked is 0 and salaried still gets basic."""
    store = await _create_store_and_role(seed_user.id)

    profile_payload = {
        "date_of_birth": "1995-06-15",
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

    assert float(slip["hours_worked"]) == 0.0
    assert float(slip["overtime_hours"]) == 0.0
    assert float(slip["gross_pay"]) == 4000.0


# ---- Commission Tests ----


async def _create_order(store_id, salesperson_id, grand_total, order_date):
    """Helper to create a completed order attributed to a salesperson."""
    async with TestSessionLocal() as session:
        order = Order(
            order_number=f"ORD-{uuid.uuid4().hex[:8]}",
            store_id=store_id,
            salesperson_id=salesperson_id,
            staff_id=salesperson_id,
            order_date=order_date,
            subtotal=grand_total,
            grand_total=grand_total,
            payment_method="cash",
            status=OrderStatus.completed,
            source=OrderSource.manual,
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)
        return order


async def _create_commission_rule(store_id, name, tiers, is_active=True):
    """Helper to create a commission rule."""
    async with TestSessionLocal() as session:
        rule = CommissionRule(
            store_id=store_id,
            name=name,
            tiers=json.dumps(tiers),
            is_active=is_active,
        )
        session.add(rule)
        await session.commit()
        await session.refresh(rule)
        return rule


@pytest.mark.asyncio
async def test_flat_commission_in_payroll(client: AsyncClient, seed_user):
    """Employee with flat commission rate earns commission on sales."""
    store = await _create_store_and_role(seed_user.id)

    # Create employee profile with 5% commission rate
    profile_payload = {
        "date_of_birth": "1995-06-15",
        "nationality": "foreigner",
        "basic_salary": "3000.00",
        "commission_rate": "5.00",
        "start_date": "2024-01-01",
    }
    resp = await client.post(
        f"/api/employees/{seed_user.id}/profile", json=profile_payload
    )
    assert resp.status_code == 201

    # Create sales orders for this employee
    await _create_order(
        store.id, seed_user.id, 10000.00,
        datetime(2026, 3, 15, 14, 0),
    )

    # Create and calculate payroll
    resp = await client.post(
        f"/api/stores/{store.id}/payroll",
        json={"period_start": "2026-03-01", "period_end": "2026-03-31"},
    )
    assert resp.status_code == 201
    run_id = resp.json()["data"]["id"]

    resp = await client.post(
        f"/api/stores/{store.id}/payroll/{run_id}/calculate"
    )
    assert resp.status_code == 200
    data = resp.json()["data"]

    slip = data["payslips"][0]
    # Commission: 10000 * 5% = 500
    assert float(slip["commission_sales"]) == 10000.0
    assert float(slip["commission_amount"]) == 500.0
    # Gross = salary + commission = 3000 + 500 = 3500
    assert float(slip["gross_pay"]) == 3500.0
    # Foreigner, no CPF
    assert float(slip["net_pay"]) == 3500.0


@pytest.mark.asyncio
async def test_tiered_commission_in_payroll(client: AsyncClient, seed_user):
    """Store-level tiered commission rules applied to payroll."""
    store = await _create_store_and_role(seed_user.id)

    # Create tiered commission rule: 5% up to $5000, 8% above $5000
    await _create_commission_rule(
        store.id,
        "Standard Tiered",
        [
            {"min": "0", "max": "5000", "rate": "0.05"},
            {"min": "5000", "max": None, "rate": "0.08"},
        ],
    )

    # Create employee (foreigner to avoid CPF complexity)
    profile_payload = {
        "date_of_birth": "1990-01-01",
        "nationality": "foreigner",
        "basic_salary": "2000.00",
        "start_date": "2024-01-01",
    }
    resp = await client.post(
        f"/api/employees/{seed_user.id}/profile", json=profile_payload
    )
    assert resp.status_code == 201

    # Create sales totalling $8000
    await _create_order(
        store.id, seed_user.id, 8000.00,
        datetime(2026, 3, 10, 10, 0),
    )

    # Calculate payroll
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

    # Tiered: 5000 * 0.05 = 250, 3000 * 0.08 = 240, total = 490
    assert float(slip["commission_sales"]) == 8000.0
    assert float(slip["commission_amount"]) == 490.0
    # Gross = 2000 + 490 = 2490
    assert float(slip["gross_pay"]) == 2490.0
    assert float(slip["net_pay"]) == 2490.0


@pytest.mark.asyncio
async def test_commission_rule_crud(client: AsyncClient, seed_user):
    """CRUD operations for commission rules."""
    store = await _create_store_and_role(seed_user.id)

    # Create
    resp = await client.post(
        f"/api/stores/{store.id}/commission-rules",
        json={
            "name": "Test Rule",
            "tiers": [{"min": "0", "max": None, "rate": "0.10"}],
        },
    )
    assert resp.status_code == 201
    rule = resp.json()["data"]
    rule_id = rule["id"]
    assert rule["name"] == "Test Rule"
    assert rule["is_active"] is True
    assert len(rule["tiers"]) == 1

    # List
    resp = await client.get(
        f"/api/stores/{store.id}/commission-rules"
    )
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1

    # Get
    resp = await client.get(
        f"/api/stores/{store.id}/commission-rules/{rule_id}"
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "Test Rule"

    # Update
    resp = await client.patch(
        f"/api/stores/{store.id}/commission-rules/{rule_id}",
        json={"name": "Updated Rule", "is_active": False},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "Updated Rule"
    assert resp.json()["data"]["is_active"] is False

    # Delete
    resp = await client.delete(
        f"/api/stores/{store.id}/commission-rules/{rule_id}"
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True


@pytest.mark.asyncio
async def test_no_sales_no_commission(client: AsyncClient, seed_user):
    """Employee with no sales gets zero commission."""
    store = await _create_store_and_role(seed_user.id)

    profile_payload = {
        "date_of_birth": "1990-01-01",
        "nationality": "foreigner",
        "basic_salary": "3000.00",
        "commission_rate": "10.00",
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

    assert float(slip["commission_sales"]) == 0.0
    assert float(slip["commission_amount"]) == 0.0
    assert float(slip["gross_pay"]) == 3000.0