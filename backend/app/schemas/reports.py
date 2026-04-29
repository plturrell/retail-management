from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel


# --- Shared ---

class ReportPeriod(BaseModel):
    from_date: str
    to_date: str


class LineItem(BaseModel):
    name: str
    amount: float


# --- Profit & Loss ---

class RevenueSection(BaseModel):
    total: float
    breakdown: list[LineItem]


class ExpenseSection(BaseModel):
    total: float
    breakdown: list[LineItem]


class LaborSection(BaseModel):
    hours_worked: float
    sales_order_count: int
    sales_amount: float
    payroll_gross: float
    cpf_employer: float
    total_labor_cost: float
    sales_per_labor_hour: float
    labor_cost_percent_of_sales: float


class ProfitLossReport(BaseModel):
    period: ReportPeriod
    revenue: RevenueSection
    expenses: ExpenseSection
    labor: LaborSection
    net_profit: float
    margin_percent: float


# --- Balance Sheet ---

class BalanceSheetSection(BaseModel):
    total: float
    breakdown: list[LineItem]


class BalanceSheetReport(BaseModel):
    as_of: str
    assets: BalanceSheetSection
    liabilities: BalanceSheetSection
    equity: BalanceSheetSection


# --- Cash Flow ---

class CashFlowSection(BaseModel):
    inflows: float
    outflows: float
    net: float


class CashFlowReport(BaseModel):
    period: ReportPeriod
    operating: CashFlowSection
    financing: CashFlowSection
    net_change: float


# --- Bank Reconciliation ---

class BankReconciliationReport(BaseModel):
    as_of: str
    bank_balance: float
    book_balance: float
    unreconciled_items: int
    unreconciled_amount: float
    difference: float


# --- Revenue by Channel ---

class ChannelRevenue(BaseModel):
    source: str
    payment_method: str
    total: float
    order_count: int


class RevenueByChannelReport(BaseModel):
    period: ReportPeriod
    channels: list[ChannelRevenue]
    grand_total: float


# --- Employee Cost Summary ---

class EmployeeCostLine(BaseModel):
    user_id: str
    full_name: str
    hours_worked: float
    sales_amount: float
    sales_order_count: int
    sales_per_hour: float
    gross_pay: float
    cpf_employer: float
    labor_cost_percent_of_sales: float
    total_cost: float


class EmployeeCostReport(BaseModel):
    period: ReportPeriod
    employees: list[EmployeeCostLine]
    total_hours_worked: float
    total_sales_amount: float
    total_sales_order_count: int
    sales_per_labor_hour: float
    total_salary: float
    total_cpf_employer: float
    total_cost: float
