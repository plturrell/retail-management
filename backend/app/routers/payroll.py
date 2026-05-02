from __future__ import annotations

import uuid as _uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from google.cloud.firestore_v1.client import Client as FirestoreClient
from google.cloud.firestore_v1.transaction import transactional as _transactional

from app.audit import log_event
from app.firestore import get_firestore_db
from app.firestore_helpers import (
    create_document,
    doc_to_dict,
    get_document,
    query_collection,
    update_document,
    delete_document,
)
from app.auth.dependencies import (
    RoleEnum,
    ensure_store_role,
    get_current_user,
    require_self_or_store_manager,
    require_store_role,
)
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.payroll import (
    CommissionRuleCreate,
    CommissionRuleRead,
    CommissionRuleUpdate,
    EmployeeProfileCreate,
    EmployeeProfileRead,
    EmployeeProfileUpdate,
    PayrollRunCreate,
    PayrollRunRead,
    PayrollRunSummary,
    PaySlipAdjust,
    PaySlipRead,
)
from app.services.commission import (
    calculate_commission,
    calculate_flat_commission,
    parse_tiers,
)
from app.services.cpf import calculate_cpf

router = APIRouter(tags=["payroll"])


# ---------------------------------------------------------------------------
# Collection path helpers
# ---------------------------------------------------------------------------

_PROFILE_COL = "employee-profiles"


def _payroll_col(store_id: UUID) -> str:
    return f"stores/{store_id}/payroll-runs"


def _payslip_col(store_id: UUID, run_id: str) -> str:
    return f"stores/{store_id}/payroll-runs/{run_id}/payslips"


def _commission_col(store_id: UUID) -> str:
    return f"stores/{store_id}/commission-rules"


def _timesheet_col(store_id: UUID) -> str:
    return f"stores/{store_id}/timesheets"


def _order_col(store_id: UUID) -> str:
    return f"stores/{store_id}/orders"


def _serialize_date(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _parse_date(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    return date.fromisoformat(val)


_DECIMAL_2DP = Decimal("0.01")


def _as_decimal(value: Any, default: str = "0") -> Decimal:
    if value in (None, ""):
        return Decimal(default)
    return Decimal(str(value))


def _quantize_2dp(value: Decimal) -> Decimal:
    return value.quantize(_DECIMAL_2DP, rounding=ROUND_HALF_UP)


def _decimal_to_float(value: Decimal) -> float:
    return float(_quantize_2dp(value))


def _safe_ratio(value: Decimal, divisor: Decimal) -> Decimal:
    if divisor <= 0:
        return Decimal("0")
    return _quantize_2dp(value / divisor)


def _safe_percent(value: Decimal, divisor: Decimal) -> Decimal:
    if divisor <= 0:
        return Decimal("0")
    return _quantize_2dp((value / divisor) * Decimal("100"))


def _user_id_str(user: Any) -> str:
    if isinstance(user, dict):
        return str(user.get("id"))
    return str(getattr(user, "id"))


def _normalize_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _profile_to_read(data: dict) -> EmployeeProfileRead:
    """Convert Firestore profile dict to EmployeeProfileRead."""
    return EmployeeProfileRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        user_id=UUID(data["user_id"]) if isinstance(data.get("user_id"), str) else data.get("user_id"),
        date_of_birth=_parse_date(data.get("date_of_birth")),
        nationality=data.get("nationality"),
        basic_salary=Decimal(str(data.get("basic_salary", 0))),
        hourly_rate=Decimal(str(data["hourly_rate"])) if data.get("hourly_rate") is not None else None,
        commission_rate=Decimal(str(data["commission_rate"])) if data.get("commission_rate") is not None else None,
        bank_account=data.get("bank_account"),
        bank_name=data.get("bank_name", "OCBC"),
        cpf_account_number=data.get("cpf_account_number"),
        start_date=_parse_date(data.get("start_date")),
        end_date=_parse_date(data.get("end_date")),
        is_active=data.get("is_active", True),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
        updated_at=data.get("updated_at"),
    )


# ---- Employee Profile endpoints ----


@router.post(
    "/api/employees/{user_id}/profile",
    response_model=DataResponse[EmployeeProfileRead],
    status_code=201,
)
async def create_employee_profile(
    user_id: UUID,
    payload: EmployeeProfileCreate,
    _: UUID = Depends(require_self_or_store_manager),
    db: FirestoreClient = Depends(get_firestore_db),
):
    doc_id = str(user_id)
    existing = get_document(_PROFILE_COL, doc_id)
    if existing is not None:
        raise HTTPException(status_code=400, detail="Employee profile already exists")

    now = datetime.now(timezone.utc)
    data = payload.model_dump(mode="json")
    data["user_id"] = str(user_id)
    data["created_at"] = now
    data["updated_at"] = now
    result = create_document(_PROFILE_COL, data, doc_id=doc_id)
    return DataResponse(data=_profile_to_read(result))


@router.get(
    "/api/employees/{user_id}/profile",
    response_model=DataResponse[EmployeeProfileRead],
)
async def get_employee_profile(
    user_id: UUID,
    _: UUID = Depends(require_self_or_store_manager),
    db: FirestoreClient = Depends(get_firestore_db),
):
    profile = get_document(_PROFILE_COL, str(user_id))
    if profile is None:
        raise HTTPException(status_code=404, detail="Employee profile not found")
    return DataResponse(data=_profile_to_read(profile))


@router.patch(
    "/api/employees/{user_id}/profile",
    response_model=DataResponse[EmployeeProfileRead],
)
async def update_employee_profile(
    user_id: UUID,
    payload: EmployeeProfileUpdate,
    _: UUID = Depends(require_self_or_store_manager),
    db: FirestoreClient = Depends(get_firestore_db),
):
    doc_id = str(user_id)
    existing = get_document(_PROFILE_COL, doc_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Employee profile not found")

    updates = payload.model_dump(exclude_unset=True, mode="json")
    updates["updated_at"] = datetime.now(timezone.utc)
    result = update_document(_PROFILE_COL, doc_id, updates)
    return DataResponse(data=_profile_to_read(result))


@router.get(
    "/api/stores/{store_id}/payroll/employees",
    response_model=PaginatedResponse[EmployeeProfileRead],
)
async def list_payroll_employees(
    store_id: UUID,
    page: int = 1,
    page_size: int = 50,
    _=Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    # Get all employees in this store from the store's employees subcollection
    emp_docs = list(db.collection(f"stores/{store_id}/employees").stream())
    user_ids = [doc.id for doc in emp_docs]

    if not user_ids:
        return PaginatedResponse(data=[], total=0, page=page, page_size=page_size)

    # Fetch profiles for these users
    profiles = []
    for uid in user_ids:
        p = get_document(_PROFILE_COL, uid)
        if p is not None:
            profiles.append(p)

    total = len(profiles)
    start = (page - 1) * page_size
    page_profiles = profiles[start : start + page_size]
    return PaginatedResponse(
        data=[_profile_to_read(p) for p in page_profiles],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Payroll-run / payslip helpers
# ---------------------------------------------------------------------------


def _run_to_summary(data: dict) -> PayrollRunSummary:
    """Convert Firestore payroll-run dict to PayrollRunSummary."""
    return PayrollRunSummary(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        store_id=UUID(data["store_id"]) if isinstance(data.get("store_id"), str) else data.get("store_id"),
        period_start=_parse_date(data.get("period_start")),
        period_end=_parse_date(data.get("period_end")),
        status=data.get("status", "draft"),
        created_by=UUID(data["created_by"]) if isinstance(data.get("created_by"), str) else data.get("created_by"),
        total_gross=Decimal(str(data.get("total_gross", 0))),
        total_cpf_employee=Decimal(str(data.get("total_cpf_employee", 0))),
        total_cpf_employer=Decimal(str(data.get("total_cpf_employer", 0))),
        total_net=Decimal(str(data.get("total_net", 0))),
        store_sales_amount=Decimal(str(data.get("store_sales_amount", 0))),
        store_sales_order_count=int(data.get("store_sales_order_count", 0) or 0),
        total_hours_worked=Decimal(str(data.get("total_hours_worked", 0))),
        total_labor_cost=Decimal(str(data.get("total_labor_cost", 0))),
        sales_per_labor_hour=Decimal(str(data.get("sales_per_labor_hour", 0))),
        labor_cost_percent_of_sales=Decimal(str(data.get("labor_cost_percent_of_sales", 0))),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
        updated_at=data.get("updated_at"),
    )


def _slip_to_read(data: dict, *, fallback_store_id: UUID | None = None) -> PaySlipRead:
    """Convert Firestore payslip dict to PaySlipRead."""
    store_id = data.get("store_id")
    if store_id is None:
        store_id = fallback_store_id
    return PaySlipRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        payroll_run_id=UUID(data["payroll_run_id"]) if isinstance(data.get("payroll_run_id"), str) else data.get("payroll_run_id"),
        store_id=UUID(store_id) if isinstance(store_id, str) else store_id,
        user_id=UUID(data["user_id"]) if isinstance(data.get("user_id"), str) else data.get("user_id"),
        basic_salary=Decimal(str(data.get("basic_salary", 0))),
        hours_worked=Decimal(str(data["hours_worked"])) if data.get("hours_worked") is not None else None,
        overtime_hours=Decimal(str(data.get("overtime_hours", 0))),
        overtime_pay=Decimal(str(data.get("overtime_pay", 0))),
        allowances=Decimal(str(data.get("allowances", 0))),
        deductions=Decimal(str(data.get("deductions", 0))),
        commission_sales=Decimal(str(data.get("commission_sales", 0))),
        commission_amount=Decimal(str(data.get("commission_amount", 0))),
        sales_order_count=int(data.get("sales_order_count", 0) or 0),
        sales_per_hour=Decimal(str(data.get("sales_per_hour", 0))),
        total_labor_cost=Decimal(str(data.get("total_labor_cost", 0))),
        labor_cost_percent_of_sales=Decimal(str(data.get("labor_cost_percent_of_sales", 0))),
        gross_pay=Decimal(str(data.get("gross_pay", 0))),
        cpf_employee=Decimal(str(data.get("cpf_employee", 0))),
        cpf_employer=Decimal(str(data.get("cpf_employer", 0))),
        net_pay=Decimal(str(data.get("net_pay", 0))),
        notes=data.get("notes"),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
        updated_at=data.get("updated_at"),
    )


def _run_to_read(run_data: dict, slips: list[dict]) -> PayrollRunRead:
    """Build a PayrollRunRead including nested payslips."""
    store_id = UUID(run_data["store_id"]) if isinstance(run_data.get("store_id"), str) else run_data.get("store_id")
    return PayrollRunRead(
        id=UUID(run_data["id"]) if isinstance(run_data.get("id"), str) else run_data.get("id"),
        store_id=store_id,
        period_start=_parse_date(run_data.get("period_start")),
        period_end=_parse_date(run_data.get("period_end")),
        status=run_data.get("status", "draft"),
        created_by=UUID(run_data["created_by"]) if isinstance(run_data.get("created_by"), str) else run_data.get("created_by"),
        approved_by=UUID(run_data["approved_by"]) if isinstance(run_data.get("approved_by"), str) else run_data.get("approved_by"),
        total_gross=Decimal(str(run_data.get("total_gross", 0))),
        total_cpf_employee=Decimal(str(run_data.get("total_cpf_employee", 0))),
        total_cpf_employer=Decimal(str(run_data.get("total_cpf_employer", 0))),
        total_net=Decimal(str(run_data.get("total_net", 0))),
        store_sales_amount=Decimal(str(run_data.get("store_sales_amount", 0))),
        store_sales_order_count=int(run_data.get("store_sales_order_count", 0) or 0),
        total_hours_worked=Decimal(str(run_data.get("total_hours_worked", 0))),
        total_labor_cost=Decimal(str(run_data.get("total_labor_cost", 0))),
        sales_per_labor_hour=Decimal(str(run_data.get("sales_per_labor_hour", 0))),
        labor_cost_percent_of_sales=Decimal(str(run_data.get("labor_cost_percent_of_sales", 0))),
        payslips=[_slip_to_read(s, fallback_store_id=store_id) for s in slips],
        created_at=run_data.get("created_at", datetime.now(timezone.utc)),
        updated_at=run_data.get("updated_at"),
    )


# ---- Payroll Run endpoints ----


@router.post(
    "/api/stores/{store_id}/payroll",
    response_model=DataResponse[PayrollRunSummary],
    status_code=201,
)
async def create_payroll_run(
    store_id: UUID,
    payload: PayrollRunCreate,
    _=Depends(require_store_role(RoleEnum.manager)),
    user=Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    now = datetime.now(timezone.utc)
    doc_id = str(_uuid.uuid4())
    user_id = _user_id_str(user)
    data = {
        "store_id": str(store_id),
        "period_start": _serialize_date(payload.period_start),
        "period_end": _serialize_date(payload.period_end),
        "status": "draft",
        "created_by": user_id,
        "approved_by": None,
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
    }
    result = create_document(_payroll_col(store_id), data, doc_id=doc_id)
    return DataResponse(data=_run_to_summary(result))


@router.get(
    "/api/stores/{store_id}/payroll",
    response_model=DataResponse[list[PayrollRunSummary]],
)
async def list_payroll_runs(
    store_id: UUID,
    status: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    _=Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    filters = []
    if status:
        filters.append(("status", "==", status))
    if period_start:
        filters.append(("period_start", ">=", _serialize_date(period_start)))
    if period_end:
        filters.append(("period_end", "<=", _serialize_date(period_end)))

    runs = query_collection(_payroll_col(store_id), filters=filters)
    return DataResponse(data=[_run_to_summary(r) for r in runs])


@router.post(
    "/api/stores/{store_id}/payroll/backfill-metrics",
    response_model=DataResponse[dict],
)
async def backfill_payroll_metrics(
    store_id: UUID,
    _=Depends(require_store_role(RoleEnum.owner)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    payroll_runs = query_collection(_payroll_col(store_id))
    if not payroll_runs:
        return DataResponse(
            data={
                "store_id": str(store_id),
                "runs_scanned": 0,
                "runs_updated": 0,
                "payslips_updated": 0,
                "runs": [],
            }
        )

    user_name_cache: dict[str, str] = {}
    runs_updated = 0
    payslips_updated = 0
    run_summaries: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    for run in payroll_runs:
        run_id_str = str(run.get("id"))
        period_start = _parse_date(run.get("period_start"))
        period_end = _parse_date(run.get("period_end"))
        if period_start is None or period_end is None:
            continue

        slip_col = _payslip_col(store_id, run_id_str)
        slips = query_collection(slip_col)
        if not slips:
            continue

        orders = _query_completed_orders_for_period(store_id, period_start, period_end)
        store_sales_amount, store_sales_order_count, user_sales, user_order_counts = _build_sales_maps(orders)
        time_entries = _query_approved_time_entries_for_period(store_id, period_start, period_end)
        user_time_entries = _group_time_entries_by_user(time_entries)

        updated_slips: list[dict] = []
        for slip in slips:
            user_id_str = str(slip.get("user_id"))
            regular_hours, overtime_hours = _compute_timesheet_hours(user_time_entries.get(user_id_str, []))
            hours_worked = regular_hours + overtime_hours
            commission_sales = user_sales.get(user_id_str, Decimal("0"))
            gross_pay = _as_decimal(slip.get("gross_pay", 0))
            cpf_employer = _as_decimal(slip.get("cpf_employer", 0))
            full_name = slip.get("full_name") or _user_full_name(user_id_str, user_name_cache)
            slip_updates = {
                "store_id": str(store_id),
                "full_name": full_name,
                "basic_salary": _decimal_to_float(_derive_base_pay_from_slip(slip)),
                "hours_worked": _decimal_to_float(hours_worked),
                "commission_sales": _decimal_to_float(commission_sales),
                "sales_order_count": user_order_counts.get(user_id_str, 0),
                **_labor_metric_fields(
                    sales_amount=commission_sales,
                    hours_worked=hours_worked,
                    gross_pay=gross_pay,
                    cpf_employer=cpf_employer,
                ),
                "updated_at": now,
            }
            updated_slip = update_document(slip_col, str(slip["id"]), slip_updates)
            updated_slips.append(updated_slip)
            payslips_updated += 1

        run_updates = {
            **_run_totals_from_slips(
                updated_slips,
                store_sales_amount=store_sales_amount,
                store_sales_order_count=store_sales_order_count,
            ),
            "updated_at": now,
        }
        update_document(_payroll_col(store_id), run_id_str, run_updates)
        runs_updated += 1
        run_summaries.append(
            {
                "payroll_run_id": run_id_str,
                "status": run.get("status", "draft"),
                "payslips_updated": len(updated_slips),
                "store_sales_amount": run_updates["store_sales_amount"],
                "total_hours_worked": run_updates["total_hours_worked"],
                "total_labor_cost": run_updates["total_labor_cost"],
                "sales_per_labor_hour": run_updates["sales_per_labor_hour"],
            }
        )

    return DataResponse(
        data={
            "store_id": str(store_id),
            "runs_scanned": len(payroll_runs),
            "runs_updated": runs_updated,
            "payslips_updated": payslips_updated,
            "runs": run_summaries,
        }
    )


@router.get(
    "/api/stores/{store_id}/payroll/{run_id}",
    response_model=DataResponse[PayrollRunRead],
)
async def get_payroll_run(
    store_id: UUID,
    run_id: UUID,
    _=Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    run_data = get_document(_payroll_col(store_id), str(run_id))
    if run_data is None:
        raise HTTPException(status_code=404, detail="Payroll run not found")

    # Fetch payslips subcollection
    slips = query_collection(_payslip_col(store_id, str(run_id)))
    return DataResponse(data=_run_to_read(run_data, slips))


def _calculate_age(dob: date, reference_date: date) -> int:
    """Calculate age in years as of reference_date."""
    age = reference_date.year - dob.year
    if (reference_date.month, reference_date.day) < (dob.month, dob.day):
        age -= 1
    return age


# Singapore standard overtime threshold: 44 hours per week
_SG_WEEKLY_OT_THRESHOLD = Decimal("44")
_SG_OT_MULTIPLIER = Decimal("1.5")


def _compute_timesheet_hours(
    entries: list[dict],
) -> tuple[Decimal, Decimal]:
    """Compute total regular hours and overtime hours from approved time entries.

    Overtime is calculated per ISO week: hours exceeding 44 in a single week
    are classified as overtime (Singapore Employment Act standard).

    Returns (regular_hours, overtime_hours).
    """
    weekly_hours: dict[tuple[int, int], Decimal] = defaultdict(Decimal)

    for entry in entries:
        clock_in = entry.get("clock_in")
        clock_out = entry.get("clock_out")
        if clock_out is None or clock_in is None:
            continue
        delta = clock_out - clock_in
        break_mins = entry.get("break_minutes", 0) or 0
        worked_seconds = max(delta.total_seconds() - break_mins * 60, 0)
        worked_hours = Decimal(str(round(worked_seconds / 3600, 2)))
        iso_year, iso_week, _ = clock_in.isocalendar()
        weekly_hours[(iso_year, iso_week)] += worked_hours

    total_regular = Decimal("0")
    total_overtime = Decimal("0")

    for _week_key, hours in weekly_hours.items():
        if hours > _SG_WEEKLY_OT_THRESHOLD:
            total_regular += _SG_WEEKLY_OT_THRESHOLD
            total_overtime += hours - _SG_WEEKLY_OT_THRESHOLD
        else:
            total_regular += hours

    return total_regular, total_overtime


def _period_bounds(period_start: date, period_end: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(period_start, datetime.min.time()),
        datetime.combine(period_end, datetime.max.time()),
    )


def _query_completed_orders_for_period(
    store_id: UUID,
    period_start: date,
    period_end: date,
) -> list[dict]:
    period_start_dt, period_end_dt = _period_bounds(period_start, period_end)
    all_orders = query_collection(
        _order_col(store_id),
        filters=[("status", "==", "completed")],
    )
    filtered_orders: list[dict] = []
    for order in all_orders:
        order_date = _normalize_datetime(order.get("order_date"))
        if order_date is not None and period_start_dt <= order_date <= period_end_dt:
            filtered_orders.append(order)
    return filtered_orders


def _build_sales_maps(
    orders: list[dict],
) -> tuple[Decimal, int, dict[str, Decimal], dict[str, int]]:
    store_sales_amount = Decimal("0")
    user_sales: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    user_order_counts: dict[str, int] = defaultdict(int)

    for order in orders:
        order_total = _as_decimal(order.get("grand_total", 0))
        store_sales_amount += order_total
        seller_id = order.get("salesperson_id") or order.get("staff_id")
        if seller_id:
            seller_id_str = str(seller_id)
            user_sales[seller_id_str] += order_total
            user_order_counts[seller_id_str] += 1

    return store_sales_amount, len(orders), user_sales, user_order_counts


def _query_approved_time_entries_for_period(
    store_id: UUID,
    period_start: date,
    period_end: date,
) -> list[dict]:
    period_start_dt, period_end_dt = _period_bounds(period_start, period_end)
    all_time_entries = query_collection(
        _timesheet_col(store_id),
        filters=[("status", "==", "approved")],
    )
    filtered_entries: list[dict] = []
    for entry in all_time_entries:
        clock_in = _normalize_datetime(entry.get("clock_in"))
        clock_out = _normalize_datetime(entry.get("clock_out"))
        if clock_in is None or clock_out is None:
            continue
        if period_start_dt <= clock_in <= period_end_dt:
            normalized_entry = dict(entry)
            normalized_entry["clock_in"] = clock_in
            normalized_entry["clock_out"] = clock_out
            filtered_entries.append(normalized_entry)
    return filtered_entries


def _group_time_entries_by_user(entries: list[dict]) -> dict[str, list[dict]]:
    user_time_entries: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        user_time_entries[str(entry.get("user_id"))].append(entry)
    return user_time_entries


def _labor_metric_fields(
    *,
    sales_amount: Decimal,
    hours_worked: Decimal,
    gross_pay: Decimal,
    cpf_employer: Decimal,
) -> dict[str, float]:
    total_labor_cost = gross_pay + cpf_employer
    sales_per_hour = _safe_ratio(sales_amount, hours_worked)
    labor_cost_percent_of_sales = _safe_percent(total_labor_cost, sales_amount)
    return {
        "sales_per_hour": _decimal_to_float(sales_per_hour),
        "total_labor_cost": _decimal_to_float(total_labor_cost),
        "labor_cost_percent_of_sales": _decimal_to_float(labor_cost_percent_of_sales),
    }


def _derive_base_pay_from_slip(slip: dict) -> Decimal:
    return _as_decimal(slip.get("gross_pay", 0)) - (
        _as_decimal(slip.get("overtime_pay", 0))
        + _as_decimal(slip.get("allowances", 0))
        + _as_decimal(slip.get("commission_amount", 0))
        - _as_decimal(slip.get("deductions", 0))
    )


def _run_totals_from_slips(
    slips: list[dict],
    *,
    store_sales_amount: Decimal,
    store_sales_order_count: int,
) -> dict[str, float | int]:
    total_gross = sum(_as_decimal(slip.get("gross_pay", 0)) for slip in slips)
    total_cpf_employee = sum(_as_decimal(slip.get("cpf_employee", 0)) for slip in slips)
    total_cpf_employer = sum(_as_decimal(slip.get("cpf_employer", 0)) for slip in slips)
    total_net = sum(_as_decimal(slip.get("net_pay", 0)) for slip in slips)
    total_hours_worked = sum(_as_decimal(slip.get("hours_worked", 0)) for slip in slips)
    total_labor_cost = total_gross + total_cpf_employer
    sales_per_labor_hour = _safe_ratio(store_sales_amount, total_hours_worked)
    labor_cost_percent_of_sales = _safe_percent(total_labor_cost, store_sales_amount)
    return {
        "total_gross": _decimal_to_float(total_gross),
        "total_cpf_employee": _decimal_to_float(total_cpf_employee),
        "total_cpf_employer": _decimal_to_float(total_cpf_employer),
        "total_net": _decimal_to_float(total_net),
        "store_sales_amount": _decimal_to_float(store_sales_amount),
        "store_sales_order_count": store_sales_order_count,
        "total_hours_worked": _decimal_to_float(total_hours_worked),
        "total_labor_cost": _decimal_to_float(total_labor_cost),
        "sales_per_labor_hour": _decimal_to_float(sales_per_labor_hour),
        "labor_cost_percent_of_sales": _decimal_to_float(labor_cost_percent_of_sales),
    }


def _user_full_name(user_id: str, cache: dict[str, str]) -> str:
    cached = cache.get(user_id)
    if cached:
        return cached
    user_doc = get_document("users", user_id) or {}
    full_name = user_doc.get("full_name", "Unknown")
    cache[user_id] = full_name
    return full_name


@router.post(
    "/api/stores/{store_id}/payroll/{run_id}/calculate",
    response_model=DataResponse[PayrollRunRead],
)
async def calculate_payroll(
    store_id: UUID,
    run_id: UUID,
    _=Depends(require_store_role(RoleEnum.manager)),
    user=Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    run_id_str = str(run_id)
    col = _payroll_col(store_id)
    run_data = get_document(col, run_id_str)
    if run_data is None:
        raise HTTPException(status_code=404, detail="Payroll run not found")

    if run_data.get("status") != "draft":
        raise HTTPException(
            status_code=400, detail="Payroll run is not in draft status"
        )

    # Get all employees in this store
    emp_docs = list(db.collection(f"stores/{store_id}/employees").stream())
    store_user_ids = [doc.id for doc in emp_docs]

    if not store_user_ids:
        raise HTTPException(
            status_code=400, detail="No employees found for this store"
        )

    # Fetch active employee profiles
    profiles = []
    for uid in store_user_ids:
        p = get_document(_PROFILE_COL, uid)
        if p is not None and p.get("is_active", True):
            profiles.append(p)

    if not profiles:
        raise HTTPException(
            status_code=400, detail="No active employee profiles found"
        )

    # Delete existing payslips for this run (recalculation)
    slip_col = _payslip_col(store_id, run_id_str)
    existing_slips = query_collection(slip_col)
    for slip in existing_slips:
        delete_document(slip_col, slip["id"])

    # Fetch active commission rules for this store
    commission_rules = query_collection(
        _commission_col(store_id),
        filters=[("is_active", "==", True)],
    )

    period_start = _parse_date(run_data.get("period_start"))
    period_end = _parse_date(run_data.get("period_end"))
    filtered_orders = _query_completed_orders_for_period(store_id, period_start, period_end)
    (
        store_sales_amount,
        store_sales_order_count,
        user_sales,
        user_order_counts,
    ) = _build_sales_maps(filtered_orders)
    filtered_entries = _query_approved_time_entries_for_period(store_id, period_start, period_end)
    user_time_entries = _group_time_entries_by_user(filtered_entries)

    now = datetime.now(timezone.utc)
    new_slips: list[dict] = []
    user_name_cache: dict[str, str] = {}

    for profile in profiles:
        uid_str = str(profile.get("user_id", profile.get("id")))
        dob = _parse_date(profile.get("date_of_birth"))
        age = _calculate_age(dob, period_end)
        basic = _as_decimal(profile.get("basic_salary", 0))
        full_name = _user_full_name(uid_str, user_name_cache)

        entries = user_time_entries.get(uid_str, [])
        regular_hours, overtime_hours = _compute_timesheet_hours(entries)
        total_hours = regular_hours + overtime_hours

        hourly_rate = profile.get("hourly_rate")
        if hourly_rate is not None:
            rate = _as_decimal(hourly_rate)
            base_pay = regular_hours * rate
            overtime_pay = overtime_hours * rate * _SG_OT_MULTIPLIER
            gross_pay = base_pay + overtime_pay
        else:
            base_pay = basic
            overtime_pay = Decimal("0")
            gross_pay = base_pay

        # CPF calculation
        cpf_ee = Decimal("0")
        cpf_er = Decimal("0")
        nationality = profile.get("nationality", "")
        if nationality != "foreigner":
            cpf_result = calculate_cpf(age=age, ordinary_wages=gross_pay)
            cpf_ee = cpf_result.employee_contribution
            cpf_er = cpf_result.employer_contribution

        # Commission calculation
        emp_sales = user_sales.get(uid_str, Decimal("0"))
        commission_amount = Decimal("0")

        if emp_sales > 0:
            if commission_rules:
                for rule in commission_rules:
                    tiers = parse_tiers(rule.get("tiers", []))
                    commission_amount += calculate_commission(emp_sales, tiers)
            else:
                cr = profile.get("commission_rate")
                if cr is not None and Decimal(str(cr)) > 0:
                    rate = Decimal(str(cr)) / Decimal("100")
                    commission_amount = calculate_flat_commission(emp_sales, rate)

        gross_pay += commission_amount
        net_pay = gross_pay - cpf_ee
        emp_order_count = user_order_counts.get(uid_str, 0)

        slip_id = str(_uuid.uuid4())
        slip_data = {
            "payroll_run_id": run_id_str,
            "store_id": str(store_id),
            "user_id": uid_str,
            "full_name": full_name,
            "basic_salary": _decimal_to_float(base_pay),
            "hours_worked": _decimal_to_float(total_hours),
            "overtime_hours": _decimal_to_float(overtime_hours),
            "overtime_pay": _decimal_to_float(overtime_pay),
            "allowances": 0,
            "deductions": 0,
            "commission_sales": _decimal_to_float(emp_sales),
            "commission_amount": _decimal_to_float(commission_amount),
            "sales_order_count": emp_order_count,
            **_labor_metric_fields(
                sales_amount=emp_sales,
                hours_worked=total_hours,
                gross_pay=gross_pay,
                cpf_employer=cpf_er,
            ),
            "gross_pay": _decimal_to_float(gross_pay),
            "cpf_employee": _decimal_to_float(cpf_ee),
            "cpf_employer": _decimal_to_float(cpf_er),
            "net_pay": _decimal_to_float(net_pay),
            "notes": None,
            "created_at": now,
            "updated_at": now,
        }
        create_document(slip_col, slip_data, doc_id=slip_id)
        slip_data["id"] = slip_id
        new_slips.append(slip_data)

    # Update run totals
    update_document(col, run_id_str, {
        **_run_totals_from_slips(
            new_slips,
            store_sales_amount=store_sales_amount,
            store_sales_order_count=store_sales_order_count,
        ),
        "status": "calculated",
        "updated_at": datetime.now(timezone.utc),
    })

    updated_run = get_document(col, run_id_str)
    return DataResponse(data=_run_to_read(updated_run, new_slips))


@router.patch(
    "/api/stores/{store_id}/payroll/{run_id}/payslips/{slip_id}",
    response_model=DataResponse[PaySlipRead],
)
async def adjust_payslip(
    store_id: UUID,
    run_id: UUID,
    slip_id: UUID,
    payload: PaySlipAdjust,
    _=Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    run_id_str = str(run_id)
    run_data = get_document(_payroll_col(store_id), run_id_str)
    if run_data is None:
        raise HTTPException(status_code=404, detail="Payroll run not found")

    slip_col = _payslip_col(store_id, run_id_str)
    slip_data = get_document(slip_col, str(slip_id))
    if slip_data is None:
        raise HTTPException(status_code=404, detail="Payslip not found")

    updates = payload.model_dump(exclude_unset=True, mode="json")
    # Merge updates into slip_data for recalculation
    for key, value in updates.items():
        slip_data[key] = value

    # Recalculate derived totals
    gross_pay = (
        _as_decimal(slip_data.get("basic_salary", 0))
        + _as_decimal(slip_data.get("overtime_pay", 0))
        + _as_decimal(slip_data.get("allowances", 0))
        + _as_decimal(slip_data.get("commission_amount", 0))
        - _as_decimal(slip_data.get("deductions", 0))
    )
    cpf_employee = _as_decimal(slip_data.get("cpf_employee", 0))
    cpf_employer = _as_decimal(slip_data.get("cpf_employer", 0))
    net_pay = gross_pay - cpf_employee
    total_labor_cost = gross_pay + cpf_employer
    sales_amount = _as_decimal(slip_data.get("commission_sales", 0))
    hours_worked = _as_decimal(slip_data.get("hours_worked", 0))
    sales_per_hour = _safe_ratio(sales_amount, hours_worked)
    labor_cost_percent_of_sales = _safe_percent(total_labor_cost, sales_amount)
    updates["gross_pay"] = _decimal_to_float(gross_pay)
    updates["net_pay"] = _decimal_to_float(net_pay)
    updates["sales_per_hour"] = _decimal_to_float(sales_per_hour)
    updates["total_labor_cost"] = _decimal_to_float(total_labor_cost)
    updates["labor_cost_percent_of_sales"] = _decimal_to_float(labor_cost_percent_of_sales)
    updates["updated_at"] = datetime.now(timezone.utc)

    updated_slip = update_document(slip_col, str(slip_id), updates)

    # Recalculate parent PayrollRun totals
    all_slips = query_collection(slip_col)
    total_gross = sum(_as_decimal(s.get("gross_pay", 0)) for s in all_slips)
    total_cpf_employee = sum(_as_decimal(s.get("cpf_employee", 0)) for s in all_slips)
    total_cpf_employer = sum(_as_decimal(s.get("cpf_employer", 0)) for s in all_slips)
    total_net = sum(_as_decimal(s.get("net_pay", 0)) for s in all_slips)
    total_hours_worked = sum(_as_decimal(s.get("hours_worked", 0)) for s in all_slips)
    total_labor_cost_run = total_gross + total_cpf_employer
    store_sales_amount = _as_decimal(run_data.get("store_sales_amount", 0))
    run_updates = {
        "total_gross": _decimal_to_float(total_gross),
        "total_cpf_employee": _decimal_to_float(total_cpf_employee),
        "total_cpf_employer": _decimal_to_float(total_cpf_employer),
        "total_net": _decimal_to_float(total_net),
        "total_hours_worked": _decimal_to_float(total_hours_worked),
        "total_labor_cost": _decimal_to_float(total_labor_cost_run),
        "sales_per_labor_hour": _decimal_to_float(_safe_ratio(store_sales_amount, total_hours_worked)),
        "labor_cost_percent_of_sales": _decimal_to_float(_safe_percent(total_labor_cost_run, store_sales_amount)),
        "updated_at": datetime.now(timezone.utc),
    }
    update_document(_payroll_col(store_id), run_id_str, run_updates)

    return DataResponse(data=_slip_to_read(updated_slip, fallback_store_id=store_id))


@router.post(
    "/api/stores/{store_id}/payroll/{run_id}/approve",
    response_model=DataResponse[PayrollRunSummary],
)
async def approve_payroll(
    store_id: UUID,
    run_id: UUID,
    _=Depends(require_store_role(RoleEnum.owner)),
    user=Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    run_id_str = str(run_id)
    col = _payroll_col(store_id)
    run_data = get_document(col, run_id_str)
    if run_data is None:
        raise HTTPException(status_code=404, detail="Payroll run not found")

    if run_data.get("status") != "calculated":
        raise HTTPException(
            status_code=400,
            detail="Payroll run must be in calculated status to approve",
        )

    created_by = run_data.get("created_by")
    user_id_str = _user_id_str(user)
    if created_by == user_id_str:
        raise HTTPException(
            status_code=400,
            detail="Payroll run cannot be approved by its creator (separation of duties)",
        )

    # Use Firestore transaction for status update
    run_ref = db.collection(col).document(run_id_str)

    @_transactional
    def _approve(transaction):
        snapshot = run_ref.get(transaction=transaction)
        if not snapshot.exists:
            raise HTTPException(status_code=404, detail="Payroll run not found")
        current = snapshot.to_dict()
        if current.get("status") != "calculated":
            raise HTTPException(
                status_code=400,
                detail="Payroll run must be in calculated status to approve",
            )
        transaction.update(run_ref, {
            "status": "approved",
            "approved_by": user_id_str,
            "updated_at": datetime.now(timezone.utc),
        })

    transaction = db.transaction()
    _approve(transaction)

    updated = doc_to_dict(run_ref.get())
    return DataResponse(data=_run_to_summary(updated))



# ---------------------------------------------------------------------------
# Commission Rule helper
# ---------------------------------------------------------------------------

def _rule_to_read(data: dict) -> CommissionRuleRead:
    """Convert Firestore commission-rule dict to CommissionRuleRead."""
    return CommissionRuleRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        store_id=UUID(data["store_id"]) if isinstance(data.get("store_id"), str) else data.get("store_id"),
        name=data.get("name", ""),
        tiers=data.get("tiers", []),
        is_active=data.get("is_active", True),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
    )


# ---- Commission Rule endpoints ----
#
# Authorization split:
#   - Reads (GET list / GET one)         → manager+ (managers need to see the
#                                          tier table to explain payslips).
#   - Writes (POST / PATCH / DELETE)     → owner+. Rate changes are payroll-
#                                          impacting; a manager must not be
#                                          able to silently lift their own
#                                          tier rate. Every mutation emits a
#                                          ``commission.rule.*`` audit event
#                                          (with old/new diff on PATCH) so
#                                          rate changes are reviewable.
#
# Single-active-rule policy:
#   New active rules cannot be created (or a deactivated rule re-activated)
#   while another active rule exists in the same store. This blocks the
#   silent multi-rule cumulation footgun in :func:`calculate_payroll`, where
#   every active rule is applied to the same sales figure. The check fires
#   only on transitions *into* the active state — editing an already-active
#   rule remains allowed so existing multi-rule stores can continue to be
#   maintained without first being unwound.


def _audit_actor(user: dict) -> dict:
    """Shape a user dict for ``log_event(actor=...)`` — mirrors users.py."""
    return {
        "id": user.get("id") if isinstance(user, dict) else getattr(user, "id", None),
        "email": user.get("email") if isinstance(user, dict) else getattr(user, "email", None),
        "firebase_uid": (
            user.get("firebase_uid") if isinstance(user, dict)
            else getattr(user, "firebase_uid", None)
        ),
    }


def _rule_audit_snapshot(rule: dict) -> dict:
    """Small, secret-free snapshot of a commission rule for audit metadata."""
    return {
        "name": rule.get("name"),
        "is_active": rule.get("is_active"),
        "tiers": rule.get("tiers", []),
    }


def _other_active_rule_exists(store_id: UUID, exclude_rule_id: str | None = None) -> bool:
    """True iff the store has an active commission rule whose id differs
    from ``exclude_rule_id``. Used to enforce single-active-rule on writes."""
    actives = query_collection(
        _commission_col(store_id),
        filters=[("is_active", "==", True)],
    )
    for r in actives:
        if exclude_rule_id is None or str(r.get("id")) != exclude_rule_id:
            return True
    return False


@router.post(
    "/api/stores/{store_id}/commission-rules",
    response_model=DataResponse[CommissionRuleRead],
    status_code=201,
)
async def create_commission_rule(
    store_id: UUID,
    payload: CommissionRuleCreate,
    request: Request,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    ensure_store_role(user, store_id, RoleEnum.owner)
    if payload.is_active and _other_active_rule_exists(store_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "Another commission rule is already active for this store. "
                "Deactivate it before creating a new active rule."
            ),
        )
    now = datetime.now(timezone.utc)
    doc_id = str(_uuid.uuid4())
    data = {
        "store_id": str(store_id),
        "name": payload.name,
        "tiers": [t.model_dump(mode="json") for t in payload.tiers],
        "is_active": payload.is_active,
        "created_at": now,
    }
    result = create_document(_commission_col(store_id), data, doc_id=doc_id)
    log_event(
        "commission.rule.create",
        actor=_audit_actor(user),
        metadata={
            "store_id": str(store_id),
            "rule_id": doc_id,
            "rule": _rule_audit_snapshot(result),
        },
        request=request,
    )
    return DataResponse(data=_rule_to_read(result))


@router.get(
    "/api/stores/{store_id}/commission-rules",
    response_model=DataResponse[list[CommissionRuleRead]],
)
async def list_commission_rules(
    store_id: UUID,
    active_only: bool = True,
    _=Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    filters = []
    if active_only:
        filters.append(("is_active", "==", True))

    rules = query_collection(_commission_col(store_id), filters=filters)
    return DataResponse(data=[_rule_to_read(r) for r in rules])


@router.get(
    "/api/stores/{store_id}/commission-rules/{rule_id}",
    response_model=DataResponse[CommissionRuleRead],
)
async def get_commission_rule(
    store_id: UUID,
    rule_id: UUID,
    _=Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    rule = get_document(_commission_col(store_id), str(rule_id))
    if rule is None:
        raise HTTPException(status_code=404, detail="Commission rule not found")
    return DataResponse(data=_rule_to_read(rule))


@router.patch(
    "/api/stores/{store_id}/commission-rules/{rule_id}",
    response_model=DataResponse[CommissionRuleRead],
)
async def update_commission_rule(
    store_id: UUID,
    rule_id: UUID,
    payload: CommissionRuleUpdate,
    request: Request,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    ensure_store_role(user, store_id, RoleEnum.owner)
    col = _commission_col(store_id)
    rule_id_str = str(rule_id)
    existing = get_document(col, rule_id_str)
    if existing is None:
        raise HTTPException(status_code=404, detail="Commission rule not found")

    updates = payload.model_dump(exclude_unset=True, mode="json")
    if "tiers" in updates and updates["tiers"] is not None:
        updates["tiers"] = [t.model_dump(mode="json") for t in payload.tiers]

    # Block inactive→active transitions when another rule is already active.
    # Edits to an already-active rule pass through so existing multi-rule
    # stores can still be maintained without first being unwound.
    activating = (
        "is_active" in updates
        and bool(updates["is_active"])
        and not bool(existing.get("is_active"))
    )
    if activating and _other_active_rule_exists(store_id, exclude_rule_id=rule_id_str):
        raise HTTPException(
            status_code=409,
            detail=(
                "Another commission rule is already active for this store. "
                "Deactivate it before activating this rule."
            ),
        )

    result = update_document(col, rule_id_str, updates)
    log_event(
        "commission.rule.update",
        actor=_audit_actor(user),
        metadata={
            "store_id": str(store_id),
            "rule_id": rule_id_str,
            "before": _rule_audit_snapshot(existing),
            "after": _rule_audit_snapshot(result),
            "changed_fields": sorted(updates.keys()),
        },
        request=request,
    )
    return DataResponse(data=_rule_to_read(result))


@router.delete(
    "/api/stores/{store_id}/commission-rules/{rule_id}",
    response_model=DataResponse[dict],
)
async def delete_commission_rule(
    store_id: UUID,
    rule_id: UUID,
    request: Request,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    ensure_store_role(user, store_id, RoleEnum.owner)
    col = _commission_col(store_id)
    rule_id_str = str(rule_id)
    existing = get_document(col, rule_id_str)
    if existing is None:
        raise HTTPException(status_code=404, detail="Commission rule not found")

    delete_document(col, rule_id_str)
    log_event(
        "commission.rule.delete",
        actor=_audit_actor(user),
        metadata={
            "store_id": str(store_id),
            "rule_id": rule_id_str,
            "rule": _rule_audit_snapshot(existing),
        },
        request=request,
    )
    return DataResponse(data={"deleted": True})
