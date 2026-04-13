from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.order import Order, OrderStatus
from app.models.payroll import PayrollRun, PaySlip
from app.models.user import RoleEnum, User, UserStoreRole
from app.auth.dependencies import get_current_user, require_store_role
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


@router.get("/profit-loss", response_model=DataResponse[ProfitLossReport])
async def profit_loss(
    store_id: UUID,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    _role: UserStoreRole = Depends(require_store_role(RoleEnum.owner)),
    db: AsyncSession = Depends(get_db),
):
    """Profit & Loss statement for the given period.

    Revenue is calculated from completed orders; expenses from payroll runs
    whose period overlaps the requested range.
    """
    range_start = datetime.combine(from_date, datetime.min.time())
    range_end = datetime.combine(to_date, datetime.max.time())

    # --- Revenue: completed orders ---
    rev_result = await db.execute(
        select(func.coalesce(func.sum(Order.grand_total), 0)).where(
            Order.store_id == store_id,
            Order.status == OrderStatus.completed,
            Order.order_date >= range_start,
            Order.order_date <= range_end,
        )
    )
    sales_revenue = float(rev_result.scalar_one())

    revenue_total = sales_revenue
    revenue_breakdown = [LineItem(name="Sales Revenue", amount=round(sales_revenue, 2))]

    # --- Expenses: payroll slips from runs overlapping the period ---
    payroll_query = (
        select(
            func.coalesce(func.sum(PaySlip.gross_pay), 0).label("total_gross"),
            func.coalesce(func.sum(PaySlip.cpf_employer), 0).label("total_cpf_er"),
        )
        .select_from(PaySlip)
        .join(PayrollRun, PaySlip.payroll_run_id == PayrollRun.id)
        .where(
            PayrollRun.store_id == store_id,
            PayrollRun.period_start <= to_date,
            PayrollRun.period_end >= from_date,
        )
    )
    payroll_result = await db.execute(payroll_query)
    row = payroll_result.one()
    total_gross = float(row.total_gross)
    total_cpf_er = float(row.total_cpf_er)

    expense_breakdown: list[LineItem] = []
    if total_gross > 0:
        expense_breakdown.append(
            LineItem(name="Salary Expense", amount=round(total_gross, 2))
        )
    if total_cpf_er > 0:
        expense_breakdown.append(
            LineItem(name="CPF Expense", amount=round(total_cpf_er, 2))
        )

    expense_total = round(total_gross + total_cpf_er, 2)
    net_profit = round(revenue_total - expense_total, 2)
    margin_percent = round((net_profit / revenue_total) * 100, 2) if revenue_total else 0.0

    return DataResponse(
        data=ProfitLossReport(
            period=ReportPeriod(
                from_date=from_date.isoformat(),
                to_date=to_date.isoformat(),
            ),
            revenue=RevenueSection(
                total=round(revenue_total, 2),
                breakdown=revenue_breakdown,
            ),
            expenses=ExpenseSection(
                total=expense_total,
                breakdown=expense_breakdown,
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
    _role: UserStoreRole = Depends(require_store_role(RoleEnum.owner)),
    db: AsyncSession = Depends(get_db),
):
    """Simplified balance sheet as of a given date.

    Assets = cumulative completed-order revenue up to as_of.
    Liabilities = unpaid payroll CPF and net pay from approved/calculated runs.
    Equity = assets - liabilities (retained earnings proxy).
    """
    as_of_end = datetime.combine(as_of, datetime.max.time())

    # Assets: cumulative revenue (proxy for cash received)
    rev_result = await db.execute(
        select(func.coalesce(func.sum(Order.grand_total), 0)).where(
            Order.store_id == store_id,
            Order.status == OrderStatus.completed,
            Order.order_date <= as_of_end,
        )
    )
    cumulative_revenue = float(rev_result.scalar_one())

    assets_breakdown = [
        LineItem(name="Cash & Receivables", amount=round(cumulative_revenue, 2)),
    ]
    assets_total = round(cumulative_revenue, 2)

    # Liabilities: CPF payable + salary payable from payroll runs up to as_of
    liab_query = (
        select(
            func.coalesce(func.sum(PaySlip.cpf_employer + PaySlip.cpf_employee), 0).label("cpf_payable"),
            func.coalesce(func.sum(PaySlip.net_pay), 0).label("salary_payable"),
        )
        .select_from(PaySlip)
        .join(PayrollRun, PaySlip.payroll_run_id == PayrollRun.id)
        .where(
            PayrollRun.store_id == store_id,
            PayrollRun.period_end <= as_of,
        )
    )
    liab_result = await db.execute(liab_query)
    liab_row = liab_result.one()
    cpf_payable = float(liab_row.cpf_payable)
    salary_payable = float(liab_row.salary_payable)

    liabilities_breakdown: list[LineItem] = []
    if cpf_payable > 0:
        liabilities_breakdown.append(
            LineItem(name="CPF Payable", amount=round(cpf_payable, 2))
        )
    if salary_payable > 0:
        liabilities_breakdown.append(
            LineItem(name="Salary Payable", amount=round(salary_payable, 2))
        )
    liabilities_total = round(cpf_payable + salary_payable, 2)

    # Equity = Assets - Liabilities
    equity_total = round(assets_total - liabilities_total, 2)
    equity_breakdown = [
        LineItem(name="Retained Earnings", amount=equity_total),
    ]

    return DataResponse(
        data=BalanceSheetReport(
            as_of=as_of.isoformat(),
            assets=BalanceSheetSection(
                total=assets_total, breakdown=assets_breakdown
            ),
            liabilities=BalanceSheetSection(
                total=liabilities_total, breakdown=liabilities_breakdown
            ),
            equity=BalanceSheetSection(
                total=equity_total, breakdown=equity_breakdown
            ),
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
    _role: UserStoreRole = Depends(require_store_role(RoleEnum.owner)),
    db: AsyncSession = Depends(get_db),
):
    """Cash flow summary for the given period."""
    range_start = datetime.combine(from_date, datetime.min.time())
    range_end = datetime.combine(to_date, datetime.max.time())

    # Inflows: completed order revenue
    inflow_result = await db.execute(
        select(func.coalesce(func.sum(Order.grand_total), 0)).where(
            Order.store_id == store_id,
            Order.status == OrderStatus.completed,
            Order.order_date >= range_start,
            Order.order_date <= range_end,
        )
    )
    inflows = float(inflow_result.scalar_one())

    # Outflows: gross pay + cpf employer from overlapping payroll runs
    outflow_query = (
        select(
            func.coalesce(func.sum(PaySlip.gross_pay), 0).label("gross"),
            func.coalesce(func.sum(PaySlip.cpf_employer), 0).label("cpf_er"),
        )
        .select_from(PaySlip)
        .join(PayrollRun, PaySlip.payroll_run_id == PayrollRun.id)
        .where(
            PayrollRun.store_id == store_id,
            PayrollRun.period_start <= to_date,
            PayrollRun.period_end >= from_date,
        )
    )
    outflow_result = await db.execute(outflow_query)
    outflow_row = outflow_result.one()
    outflows = float(outflow_row.gross) + float(outflow_row.cpf_er)

    operating_net = round(inflows - outflows, 2)

    return DataResponse(
        data=CashFlowReport(
            period=ReportPeriod(
                from_date=from_date.isoformat(),
                to_date=to_date.isoformat(),
            ),
            operating=CashFlowSection(
                inflows=round(inflows, 2),
                outflows=round(outflows, 2),
                net=operating_net,
            ),
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
    _role: UserStoreRole = Depends(require_store_role(RoleEnum.owner)),
    db: AsyncSession = Depends(get_db),
):
    """Bank reconciliation summary.

    TODO: Integrate with BankTransaction model once banking module is built.
    Currently returns placeholder values indicating no reconciliation data.
    """
    return DataResponse(
        data=BankReconciliationReport(
            as_of=as_of.isoformat(),
            bank_balance=0.0,
            book_balance=0.0,
            unreconciled_items=0,
            unreconciled_amount=0.0,
            difference=0.0,
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
    _role: UserStoreRole = Depends(require_store_role(RoleEnum.owner)),
    db: AsyncSession = Depends(get_db),
):
    """Revenue grouped by order source and payment method."""
    range_start = datetime.combine(from_date, datetime.min.time())
    range_end = datetime.combine(to_date, datetime.max.time())

    query = (
        select(
            Order.source,
            Order.payment_method,
            func.coalesce(func.sum(Order.grand_total), 0).label("total"),
            func.count(Order.id).label("order_count"),
        )
        .where(
            Order.store_id == store_id,
            Order.status == OrderStatus.completed,
            Order.order_date >= range_start,
            Order.order_date <= range_end,
        )
        .group_by(Order.source, Order.payment_method)
    )

    result = await db.execute(query)
    rows = result.all()

    channels = [
        ChannelRevenue(
            source=row.source.value if hasattr(row.source, "value") else str(row.source),
            payment_method=row.payment_method,
            total=round(float(row.total), 2),
            order_count=int(row.order_count),
        )
        for row in rows
    ]

    grand_total = round(sum(c.total for c in channels), 2)

    return DataResponse(
        data=RevenueByChannelReport(
            period=ReportPeriod(
                from_date=from_date.isoformat(),
                to_date=to_date.isoformat(),
            ),
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
    _role: UserStoreRole = Depends(require_store_role(RoleEnum.owner)),
    db: AsyncSession = Depends(get_db),
):
    """Employee cost summary for the given period."""
    query = (
        select(
            PaySlip.user_id,
            User.full_name,
            func.coalesce(func.sum(PaySlip.gross_pay), 0).label("total_gross"),
            func.coalesce(func.sum(PaySlip.cpf_employer), 0).label("total_cpf_er"),
        )
        .select_from(PaySlip)
        .join(PayrollRun, PaySlip.payroll_run_id == PayrollRun.id)
        .join(User, PaySlip.user_id == User.id)
        .where(
            PayrollRun.store_id == store_id,
            PayrollRun.period_start <= to_date,
            PayrollRun.period_end >= from_date,
        )
        .group_by(PaySlip.user_id, User.full_name)
    )

    result = await db.execute(query)
    rows = result.all()

    employees = []
    sum_salary = 0.0
    sum_cpf = 0.0
    for row in rows:
        gross = round(float(row.total_gross), 2)
        cpf_er = round(float(row.total_cpf_er), 2)
        cost = round(gross + cpf_er, 2)
        employees.append(
            EmployeeCostLine(
                user_id=str(row.user_id),
                full_name=row.full_name,
                gross_pay=gross,
                cpf_employer=cpf_er,
                total_cost=cost,
            )
        )
        sum_salary += gross
        sum_cpf += cpf_er

    return DataResponse(
        data=EmployeeCostReport(
            period=ReportPeriod(
                from_date=from_date.isoformat(),
                to_date=to_date.isoformat(),
            ),
            employees=employees,
            total_salary=round(sum_salary, 2),
            total_cpf_employer=round(sum_cpf, 2),
            total_cost=round(sum_salary + sum_cpf, 2),
        )
    )
