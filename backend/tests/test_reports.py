from __future__ import annotations

from datetime import datetime

import pytest
from httpx import AsyncClient

from tests.firestore_payroll_support import (
    override_owner_user,
    seed_approved_time_entries,
    seed_completed_order,
    seed_employee_profile,
    seed_store_scenario,
)


@pytest.mark.asyncio
async def test_profit_loss_report_includes_store_labor_metrics(client: AsyncClient) -> None:
    scenario = seed_store_scenario()
    seed_employee_profile(user_id=scenario.employee_id, basic_salary="3000.00")
    seed_completed_order(
        store_id=scenario.store_id,
        salesperson_id=scenario.employee_id,
        grand_total=10000.0,
        order_date=datetime(2026, 3, 15, 14, 0),
    )
    seed_approved_time_entries(
        store_id=scenario.store_id,
        user_id=scenario.employee_id,
        entries=[
            (datetime(2026, 3, 2, 9, 0), datetime(2026, 3, 2, 17, 30), 30),
            (datetime(2026, 3, 3, 9, 0), datetime(2026, 3, 3, 17, 30), 30),
        ],
    )

    with override_owner_user(owner_id=scenario.owner_id, store_id=scenario.store_id):
        resp = await client.post(
            f"/api/stores/{scenario.store_id}/payroll",
            json={"period_start": "2026-03-01", "period_end": "2026-03-31"},
        )
        assert resp.status_code == 201, resp.text
        run_id = resp.json()["data"]["id"]

        resp = await client.post(
            f"/api/stores/{scenario.store_id}/payroll/{run_id}/calculate"
        )
        assert resp.status_code == 200, resp.text

        resp = await client.get(
            f"/api/stores/{scenario.store_id}/reports/profit-loss",
            params={"from": "2026-03-01", "to": "2026-03-31"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["revenue"]["total"] == 10000.0
    assert data["expenses"]["total"] == 3000.0
    assert data["labor"]["hours_worked"] == 16.0
    assert data["labor"]["sales_order_count"] == 1
    assert data["labor"]["sales_amount"] == 10000.0
    assert data["labor"]["payroll_gross"] == 3000.0
    assert data["labor"]["cpf_employer"] == 0.0
    assert data["labor"]["total_labor_cost"] == 3000.0
    assert data["labor"]["sales_per_labor_hour"] == 625.0
    assert data["labor"]["labor_cost_percent_of_sales"] == 30.0
    assert data["net_profit"] == 7000.0
    assert data["margin_percent"] == 70.0


@pytest.mark.asyncio
async def test_employee_cost_report_tracks_salesperson_sales_and_hours(client: AsyncClient) -> None:
    scenario = seed_store_scenario(store_code="BREEZE-01", store_name="Breeze", store_location="Breeze by East")
    seed_employee_profile(
        user_id=scenario.employee_id,
        basic_salary="2000.00",
        commission_rate="5.00",
    )
    seed_completed_order(
        store_id=scenario.store_id,
        salesperson_id=scenario.employee_id,
        grand_total=5000.0,
        order_date=datetime(2026, 3, 12, 11, 0),
    )
    seed_approved_time_entries(
        store_id=scenario.store_id,
        user_id=scenario.employee_id,
        entries=[
            (datetime(2026, 3, 10, 9, 0), datetime(2026, 3, 10, 17, 30), 30),
            (datetime(2026, 3, 11, 9, 0), datetime(2026, 3, 11, 17, 30), 30),
        ],
    )

    with override_owner_user(owner_id=scenario.owner_id, store_id=scenario.store_id):
        resp = await client.post(
            f"/api/stores/{scenario.store_id}/payroll",
            json={"period_start": "2026-03-01", "period_end": "2026-03-31"},
        )
        assert resp.status_code == 201, resp.text
        run_id = resp.json()["data"]["id"]

        resp = await client.post(
            f"/api/stores/{scenario.store_id}/payroll/{run_id}/calculate"
        )
        assert resp.status_code == 200, resp.text

        resp = await client.get(
            f"/api/stores/{scenario.store_id}/reports/employee-costs",
            params={"from": "2026-03-01", "to": "2026-03-31"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total_hours_worked"] == 16.0
    assert data["total_sales_amount"] == 5000.0
    assert data["total_sales_order_count"] == 1
    assert data["sales_per_labor_hour"] == 312.5
    assert data["total_salary"] == 2250.0
    assert data["total_cpf_employer"] == 0.0
    assert data["total_cost"] == 2250.0
    assert len(data["employees"]) == 1

    employee = data["employees"][0]
    assert employee["user_id"] == str(scenario.employee_id)
    assert employee["full_name"] == "Test User"
    assert employee["hours_worked"] == 16.0
    assert employee["sales_amount"] == 5000.0
    assert employee["sales_order_count"] == 1
    assert employee["sales_per_hour"] == 312.5
    assert employee["gross_pay"] == 2250.0
    assert employee["cpf_employer"] == 0.0
    assert employee["labor_cost_percent_of_sales"] == 45.0
    assert employee["total_cost"] == 2250.0
