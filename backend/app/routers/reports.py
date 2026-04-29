from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from google.cloud.firestore_v1.client import Client as FirestoreClient

from app.firestore import get_firestore_db
from app.firestore_helpers import get_document, query_collection
from app.auth.dependencies import RoleEnum, require_store_role
from app.schemas.common import DataResponse
from app.schemas.reports import (
    BalanceSheetReport,
    BalanceSheetSection,
    BankReconciliationReport,
    CashFlowReport,
    CashFlowSection,
    ChannelRevenue,
    EmployeeCostLine,
    EmployeeCostReport,
    ExpenseSection,
    LaborSection,
    LineItem,
    ProfitLossReport,
    ReportPeriod,
    RevenueByChannelReport,
    RevenueSection,
)

router = APIRouter(
    prefix="/api/stores/{store_id}/reports",
    tags=["reports"],
)


# ---------------------------------------------------------------------------
# Profit & Loss
# ---------------------------------------------------------------------------


def _query_orders(store_id: UUID, status: str = "completed", date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    """Query orders collection for a store with client-side date filtering."""
    orders = query_collection(f"stores/{store_id}/orders", filters=[("status", "==", status)])

    date_from_value = date.fromisoformat(date_from) if date_from else None
    date_to_value = date.fromisoformat(date_to) if date_to else None

    filtered_orders = []
    for order in orders:
        order_date_value = order.get("order_date")
        if order_date_value is None:
            continue
        if isinstance(order_date_value, str):
            order_date_value = datetime.fromisoformat(order_date_value)
        order_day = order_date_value.date() if hasattr(order_date_value, "date") else order_date_value
        if date_from_value and order_day < date_from_value:
            continue
        if date_to_value and order_day > date_to_value:
            continue
        filtered_orders.append(order)
    return filtered_orders


def _query_payroll_runs(store_id: UUID, period_start_before: str | None = None, period_end_after: str | None = None) -> list[dict]:
    """Query payroll runs for a store with client-side overlap filtering."""
    payroll_runs = query_collection(f"stores/{store_id}/payroll-runs")

    period_start_before_value = date.fromisoformat(period_start_before) if period_start_before else None
    period_end_after_value = date.fromisoformat(period_end_after) if period_end_after else None

    filtered_runs = []
    for run in payroll_runs:
        run_period_start = run.get("period_start")
        run_period_end = run.get("period_end")
        if run_period_start is None or run_period_end is None:
            continue
        if isinstance(run_period_start, str):
            run_period_start = date.fromisoformat(run_period_start)
        if isinstance(run_period_end, str):
            run_period_end = date.fromisoformat(run_period_end)
        if period_start_before_value and run_period_start > period_start_before_value:
            continue
        if period_end_after_value and run_period_end < period_end_after_value:
            continue
        filtered_runs.append(run)
    return filtered_runs


def _sum_payroll_run_metrics(payroll_runs: list[dict]) -> dict[str, float]:
    """Summarize payroll metrics from store payroll runs."""
    totals = {
        "total_gross": 0.0,
        "total_cpf_employee": 0.0,
        "total_cpf_employer": 0.0,
        "total_net": 0.0,
        "total_hours_worked": 0.0,
        "total_labor_cost": 0.0,
    }
    for run in payroll_runs:
        gross = float(run.get("total_gross", 0) or 0)
        cpf_employee = float(run.get("total_cpf_employee", 0) or 0)
        cpf_employer = float(run.get("total_cpf_employer", 0) or 0)
        totals["total_gross"] += gross
        totals["total_cpf_employee"] += cpf_employee
        totals["total_cpf_employer"] += cpf_employer
        totals["total_net"] += float(run.get("total_net", 0) or 0)
        totals["total_hours_worked"] += float(run.get("total_hours_worked", 0) or 0)
        totals["total_labor_cost"] += float(run.get("total_labor_cost", gross + cpf_employer) or 0)
    return totals


def _payslip_collection(store_id: UUID, run_id: str) -> str:
    return f"stores/{store_id}/payroll-runs/{run_id}/payslips"


@router.get("/profit-loss", response_model=DataResponse[ProfitLossReport])
async def profit_loss(
    store_id: UUID,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    _role: dict = Depends(require_store_role(RoleEnum.owner)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Profit & Loss statement for the given period."""
    # Revenue: completed orders
    orders = _query_orders(store_id, "completed", from_date.isoformat(), to_date.isoformat())
    sales_revenue = sum(float(o.get("grand_total", 0)) for o in orders)

    revenue_total = sales_revenue
    revenue_breakdown = [LineItem(name="Sales Revenue", amount=round(sales_revenue, 2))]

    # Expenses: payroll
    payroll_runs = _query_payroll_runs(store_id, to_date.isoformat(), from_date.isoformat())
    payroll_totals = _sum_payroll_run_metrics(payroll_runs)
    total_gross = round(payroll_totals["total_gross"], 2)
    total_cpf_er = round(payroll_totals["total_cpf_employer"], 2)
    total_hours_worked = round(payroll_totals["total_hours_worked"], 2)

    expense_breakdown: list[LineItem] = []
    if total_gross > 0:
        expense_breakdown.append(LineItem(name="Salary Expense", amount=round(total_gross, 2)))
    if total_cpf_er > 0:
        expense_breakdown.append(LineItem(name="CPF Expense", amount=round(total_cpf_er, 2)))

    expense_total = round(payroll_totals["total_labor_cost"], 2)
    net_profit = round(revenue_total - expense_total, 2)
    margin_percent = round((net_profit / revenue_total) * 100, 2) if revenue_total else 0.0
    sales_per_labor_hour = round(revenue_total / total_hours_worked, 2) if total_hours_worked else 0.0
    labor_cost_percent = round((expense_total / revenue_total) * 100, 2) if revenue_total else 0.0

    return DataResponse(
        data=ProfitLossReport(
            period=ReportPeriod(from_date=from_date.isoformat(), to_date=to_date.isoformat()),
            revenue=RevenueSection(total=round(revenue_total, 2), breakdown=revenue_breakdown),
            expenses=ExpenseSection(total=expense_total, breakdown=expense_breakdown),
            labor=LaborSection(
                hours_worked=total_hours_worked,
                sales_order_count=len(orders),
                sales_amount=round(revenue_total, 2),
                payroll_gross=total_gross,
                cpf_employer=total_cpf_er,
                total_labor_cost=expense_total,
                sales_per_labor_hour=sales_per_labor_hour,
                labor_cost_percent_of_sales=labor_cost_percent,
            ),
            net_profit=net_profit,
            margin_percent=margin_percent,
        )
    )


# ---------------------------------------------------------------------------
# Balance Sheet
# ---------------------------------------------------------------------------


@router.get("/balance-sheet", response_model=DataResponse[BalanceSheetReport])
async def balance_sheet(
    store_id: UUID,
    as_of: date = Query(...),
    _role: dict = Depends(require_store_role(RoleEnum.owner)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Simplified balance sheet as of a given date."""
    # Assets: cumulative revenue
    orders = _query_orders(store_id, "completed", date_to=as_of.isoformat())
    cumulative_revenue = sum(float(o.get("grand_total", 0)) for o in orders)

    assets_breakdown = [LineItem(name="Cash & Receivables", amount=round(cumulative_revenue, 2))]
    assets_total = round(cumulative_revenue, 2)

    # Liabilities: payroll runs up to as_of
    payroll_runs = query_collection(
        f"stores/{store_id}/payroll-runs",
        filters=[("period_end", "<=", as_of.isoformat())],
    )
    payroll_totals = _sum_payroll_run_metrics(payroll_runs)
    cpf_payable = round(
        payroll_totals["total_cpf_employer"] + payroll_totals["total_cpf_employee"], 2
    )
    salary_payable = round(payroll_totals["total_net"], 2)

    liabilities_breakdown: list[LineItem] = []
    if cpf_payable > 0:
        liabilities_breakdown.append(LineItem(name="CPF Payable", amount=round(cpf_payable, 2)))
    if salary_payable > 0:
        liabilities_breakdown.append(LineItem(name="Salary Payable", amount=round(salary_payable, 2)))
    liabilities_total = round(cpf_payable + salary_payable, 2)

    equity_total = round(assets_total - liabilities_total, 2)
    equity_breakdown = [LineItem(name="Retained Earnings", amount=equity_total)]

    return DataResponse(
        data=BalanceSheetReport(
            as_of=as_of.isoformat(),
            assets=BalanceSheetSection(total=assets_total, breakdown=assets_breakdown),
            liabilities=BalanceSheetSection(total=liabilities_total, breakdown=liabilities_breakdown),
            equity=BalanceSheetSection(total=equity_total, breakdown=equity_breakdown),
        )
    )


# ---------------------------------------------------------------------------
# Cash Flow
# ---------------------------------------------------------------------------


@router.get("/cash-flow", response_model=DataResponse[CashFlowReport])
async def cash_flow(
    store_id: UUID,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    _role: dict = Depends(require_store_role(RoleEnum.owner)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Cash flow summary for the given period."""
    orders = _query_orders(store_id, "completed", from_date.isoformat(), to_date.isoformat())
    inflows = sum(float(o.get("grand_total", 0)) for o in orders)

    payroll_runs = _query_payroll_runs(store_id, to_date.isoformat(), from_date.isoformat())
    payroll_totals = _sum_payroll_run_metrics(payroll_runs)
    outflows = round(payroll_totals["total_labor_cost"], 2)

    operating_net = round(inflows - outflows, 2)

    return DataResponse(
        data=CashFlowReport(
            period=ReportPeriod(from_date=from_date.isoformat(), to_date=to_date.isoformat()),
            operating=CashFlowSection(inflows=round(inflows, 2), outflows=round(outflows, 2), net=operating_net),
            financing=CashFlowSection(inflows=0, outflows=0, net=0),
            net_change=operating_net,
        )
    )


# ---------------------------------------------------------------------------
# Bank Reconciliation
# ---------------------------------------------------------------------------


@router.get(
    "/bank-reconciliation",
    response_model=DataResponse[BankReconciliationReport],
)
async def bank_reconciliation(
    store_id: UUID,
    as_of: date = Query(...),
    _role: dict = Depends(require_store_role(RoleEnum.owner)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Bank reconciliation summary."""
    # Query banking transactions for reconciliation data
    all_txns = query_collection(f"stores/{store_id}/banking", filters=[("transaction_date", "<=", as_of.isoformat())])
    bank_balance = sum(float(t.get("amount", 0)) for t in all_txns)
    reconciled = [t for t in all_txns if t.get("is_reconciled")]
    unreconciled = [t for t in all_txns if not t.get("is_reconciled")]
    book_balance = sum(float(t.get("amount", 0)) for t in reconciled)
    unreconciled_amount = sum(float(t.get("amount", 0)) for t in unreconciled)

    return DataResponse(
        data=BankReconciliationReport(
            as_of=as_of.isoformat(),
            bank_balance=round(bank_balance, 2),
            book_balance=round(book_balance, 2),
            unreconciled_items=len(unreconciled),
            unreconciled_amount=round(unreconciled_amount, 2),
            difference=round(bank_balance - book_balance, 2),
        )
    )


# ---------------------------------------------------------------------------
# Revenue by Payment Channel
# ---------------------------------------------------------------------------


@router.get(
    "/revenue-by-channel",
    response_model=DataResponse[RevenueByChannelReport],
)
async def revenue_by_channel(
    store_id: UUID,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    _role: dict = Depends(require_store_role(RoleEnum.owner)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Revenue grouped by order source and payment method."""
    orders = _query_orders(store_id, "completed", from_date.isoformat(), to_date.isoformat())

    # Client-side group-by
    channel_map: dict[tuple[str, str], tuple[float, int]] = {}
    for o in orders:
        source = o.get("source", "unknown")
        pm = o.get("payment_method", "unknown")
        key = (source, pm)
        total, count = channel_map.get(key, (0.0, 0))
        channel_map[key] = (total + float(o.get("grand_total", 0)), count + 1)

    channels = [
        ChannelRevenue(
            source=source,
            payment_method=pm,
            total=round(total, 2),
            order_count=count,
        )
        for (source, pm), (total, count) in channel_map.items()
    ]
    grand_total = round(sum(c.total for c in channels), 2)

    return DataResponse(
        data=RevenueByChannelReport(
            period=ReportPeriod(from_date=from_date.isoformat(), to_date=to_date.isoformat()),
            channels=channels,
            grand_total=grand_total,
        )
    )


# ---------------------------------------------------------------------------
# Employee Cost Summary
# ---------------------------------------------------------------------------


@router.get(
    "/employee-costs",
    response_model=DataResponse[EmployeeCostReport],
)
async def employee_costs(
    store_id: UUID,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    _role: dict = Depends(require_store_role(RoleEnum.owner)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Employee cost summary for the given period."""
    payroll_runs = _query_payroll_runs(store_id, to_date.isoformat(), from_date.isoformat())

    # Aggregate per user from payslip subcollections
    user_map: dict[str, dict] = {}
    for run in payroll_runs:
        run_id = str(run.get("id"))
        for slip in query_collection(_payslip_collection(store_id, run_id)):
            uid = slip.get("user_id", "unknown")
            if uid not in user_map:
                user_doc = get_document("users", uid) or {}
                user_map[uid] = {
                    "full_name": slip.get("full_name") or user_doc.get("full_name", "Unknown"),
                    "hours_worked": 0.0,
                    "sales_amount": 0.0,
                    "sales_order_count": 0,
                    "gross": 0.0,
                    "cpf_er": 0.0,
                }
            user_map[uid]["hours_worked"] += float(slip.get("hours_worked", 0) or 0)
            user_map[uid]["sales_amount"] += float(slip.get("commission_sales", 0) or 0)
            user_map[uid]["sales_order_count"] += int(slip.get("sales_order_count", 0) or 0)
            user_map[uid]["gross"] += float(slip.get("gross_pay", 0))
            user_map[uid]["cpf_er"] += float(slip.get("cpf_employer", 0))

    employees = []
    sum_hours = 0.0
    sum_sales = 0.0
    sum_orders = 0
    sum_salary = 0.0
    sum_cpf = 0.0
    for uid, info in user_map.items():
        hours_worked = round(info["hours_worked"], 2)
        sales_amount = round(info["sales_amount"], 2)
        sales_order_count = info["sales_order_count"]
        gross = round(info["gross"], 2)
        cpf_er = round(info["cpf_er"], 2)
        cost = round(gross + cpf_er, 2)
        sales_per_hour = round(sales_amount / hours_worked, 2) if hours_worked else 0.0
        labor_cost_percent_of_sales = round((cost / sales_amount) * 100, 2) if sales_amount else 0.0
        employees.append(EmployeeCostLine(
            user_id=uid,
            full_name=info["full_name"],
            hours_worked=hours_worked,
            sales_amount=sales_amount,
            sales_order_count=sales_order_count,
            sales_per_hour=sales_per_hour,
            gross_pay=gross,
            cpf_employer=cpf_er,
            labor_cost_percent_of_sales=labor_cost_percent_of_sales,
            total_cost=cost,
        ))
        sum_hours += hours_worked
        sum_sales += sales_amount
        sum_orders += sales_order_count
        sum_salary += gross
        sum_cpf += cpf_er

    employees.sort(key=lambda employee: employee.sales_amount, reverse=True)

    return DataResponse(
        data=EmployeeCostReport(
            period=ReportPeriod(from_date=from_date.isoformat(), to_date=to_date.isoformat()),
            employees=employees,
            total_hours_worked=round(sum_hours, 2),
            total_sales_amount=round(sum_sales, 2),
            total_sales_order_count=sum_orders,
            sales_per_labor_hour=round(sum_sales / sum_hours, 2) if sum_hours else 0.0,
            total_salary=round(sum_salary, 2),
            total_cpf_employer=round(sum_cpf, 2),
            total_cost=round(sum_salary + sum_cpf, 2),
        )
    )
