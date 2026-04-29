from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient

import app.firestore as _fs
from app.firestore_helpers import create_document, get_document


def _firestore_available() -> bool:
    """True iff a real Firestore client can be obtained (creds present)."""
    try:
        client = _fs._get_db()
    except Exception:
        return False
    return client is not None


pytestmark = pytest.mark.skipif(
    not _firestore_available(),
    reason="Integration test: requires real Firestore credentials or emulator",
)
from tests.firestore_payroll_support import (
    override_owner_user,
    seed_approved_time_entries,
    seed_completed_order,
    seed_employee_profile,
    seed_store_scenario,
)


@pytest.mark.asyncio
async def test_backfill_metrics_recomputes_historical_runs_without_changing_status(
    client: AsyncClient,
) -> None:
    scenario = seed_store_scenario(store_code="ONLINE-01", store_name="Online", store_location="Website")
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

    run_id = str(uuid4())
    slip_id = str(uuid4())
    now = datetime.now(timezone.utc)
    create_document(
        f"stores/{scenario.store_id}/payroll-runs",
        {
            "id": run_id,
            "store_id": str(scenario.store_id),
            "period_start": "2026-03-01",
            "period_end": "2026-03-31",
            "status": "approved",
            "created_by": str(scenario.owner_id),
            "approved_by": str(scenario.owner_id),
            "total_gross": 0,
            "total_cpf_employee": 0,
            "total_cpf_employer": 0,
            "total_net": 0,
            "store_sales_amount": 0,
            "store_sales_order_count": 0,
            "total_hours_worked": 0,
            "total_labor_cost": 0,
            "sales_per_labor_hour": 0,
            "labor_cost_percent_of_sales": 0,
            "created_at": now,
            "updated_at": now,
        },
        doc_id=run_id,
    )
    create_document(
        f"stores/{scenario.store_id}/payroll-runs/{run_id}/payslips",
        {
            "id": slip_id,
            "payroll_run_id": run_id,
            "user_id": str(scenario.employee_id),
            "basic_salary": 0,
            "hours_worked": 0,
            "overtime_hours": 0,
            "overtime_pay": 0,
            "allowances": 0,
            "deductions": 0,
            "commission_sales": 0,
            "commission_amount": 250.0,
            "sales_order_count": 0,
            "sales_per_hour": 0,
            "total_labor_cost": 0,
            "labor_cost_percent_of_sales": 0,
            "gross_pay": 2250.0,
            "cpf_employee": 0,
            "cpf_employer": 0,
            "net_pay": 2250.0,
            "notes": None,
            "created_at": now,
            "updated_at": now,
        },
        doc_id=slip_id,
    )

    with override_owner_user(owner_id=scenario.owner_id, store_id=scenario.store_id):
        resp = await client.post(
            f"/api/stores/{scenario.store_id}/payroll/backfill-metrics",
        )

    assert resp.status_code == 200, resp.text
    payload = resp.json()["data"]
    assert payload["store_id"] == str(scenario.store_id)
    assert payload["runs_scanned"] == 1
    assert payload["runs_updated"] == 1
    assert payload["payslips_updated"] == 1

    updated_run = get_document(f"stores/{scenario.store_id}/payroll-runs", run_id)
    updated_slip = get_document(
        f"stores/{scenario.store_id}/payroll-runs/{run_id}/payslips",
        slip_id,
    )

    assert updated_run is not None
    assert updated_run["status"] == "approved"
    assert updated_run["store_sales_amount"] == 5000.0
    assert updated_run["store_sales_order_count"] == 1
    assert updated_run["total_hours_worked"] == 16.0
    assert updated_run["total_labor_cost"] == 2250.0
    assert updated_run["sales_per_labor_hour"] == 312.5
    assert updated_run["labor_cost_percent_of_sales"] == 45.0

    assert updated_slip is not None
    assert updated_slip["store_id"] == str(scenario.store_id)
    assert updated_slip["full_name"] == "Test User"
    assert updated_slip["basic_salary"] == 2000.0
    assert updated_slip["hours_worked"] == 16.0
    assert updated_slip["commission_sales"] == 5000.0
    assert updated_slip["sales_order_count"] == 1
    assert updated_slip["sales_per_hour"] == 312.5
    assert updated_slip["total_labor_cost"] == 2250.0
    assert updated_slip["labor_cost_percent_of_sales"] == 45.0
