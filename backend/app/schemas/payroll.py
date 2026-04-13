from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import TimestampMixin, UUIDMixin


def _mask_sensitive(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) <= 4:
        return "****"
    return "*" * (len(value) - 4) + value[-4:]


# ---------- EmployeeProfile ----------


class EmployeeProfileCreate(BaseModel):
    date_of_birth: date
    nationality: str = Field(..., pattern="^(citizen|pr|foreigner)$")
    basic_salary: Decimal = Field(..., ge=0)
    hourly_rate: Optional[Decimal] = None
    commission_rate: Optional[Decimal] = Field(None, ge=0, le=100)
    bank_account: Optional[str] = None
    bank_name: str = "OCBC"
    cpf_account_number: Optional[str] = None
    start_date: date
    end_date: Optional[date] = None
    is_active: bool = True


class EmployeeProfileRead(UUIDMixin, TimestampMixin):
    user_id: UUID
    date_of_birth: date
    nationality: str
    basic_salary: Decimal
    hourly_rate: Optional[Decimal] = None
    commission_rate: Optional[Decimal] = None
    bank_account: Optional[str] = None
    bank_name: str
    cpf_account_number: Optional[str] = None
    start_date: date
    end_date: Optional[date] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def mask_pii(self) -> "EmployeeProfileRead":
        self.bank_account = _mask_sensitive(self.bank_account)
        self.cpf_account_number = _mask_sensitive(self.cpf_account_number)
        return self


class EmployeeProfileReadFull(UUIDMixin, TimestampMixin):
    """Unmasked version for privileged payroll calculation."""
    user_id: UUID
    date_of_birth: date
    nationality: str
    basic_salary: Decimal
    hourly_rate: Optional[Decimal] = None
    commission_rate: Optional[Decimal] = None
    bank_account: Optional[str] = None
    bank_name: str
    cpf_account_number: Optional[str] = None
    start_date: date
    end_date: Optional[date] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class EmployeeProfileUpdate(BaseModel):
    date_of_birth: Optional[date] = None
    nationality: Optional[str] = Field(None, pattern="^(citizen|pr|foreigner)$")
    basic_salary: Optional[Decimal] = Field(None, ge=0)
    hourly_rate: Optional[Decimal] = None
    commission_rate: Optional[Decimal] = Field(None, ge=0, le=100)
    bank_account: Optional[str] = None
    bank_name: Optional[str] = None
    cpf_account_number: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_active: Optional[bool] = None


# ---------- PayrollRun ----------


class PayrollRunCreate(BaseModel):
    period_start: date
    period_end: date


class PayrollRunRead(UUIDMixin, TimestampMixin):
    store_id: UUID
    period_start: date
    period_end: date
    status: str
    created_by: UUID
    approved_by: Optional[UUID] = None
    total_gross: Decimal
    total_cpf_employee: Decimal
    total_cpf_employer: Decimal
    total_net: Decimal
    payslips: list[PaySlipRead] = []

    model_config = ConfigDict(from_attributes=True)


class PayrollRunSummary(UUIDMixin, TimestampMixin):
    store_id: UUID
    period_start: date
    period_end: date
    status: str
    created_by: UUID
    total_gross: Decimal
    total_cpf_employee: Decimal
    total_cpf_employer: Decimal
    total_net: Decimal

    model_config = ConfigDict(from_attributes=True)


# ---------- PaySlip ----------


class PaySlipRead(UUIDMixin, TimestampMixin):
    payroll_run_id: UUID
    user_id: UUID
    basic_salary: Decimal
    hours_worked: Optional[Decimal] = None
    overtime_hours: Decimal
    overtime_pay: Decimal
    allowances: Decimal
    deductions: Decimal
    commission_sales: Decimal = Decimal("0")
    commission_amount: Decimal = Decimal("0")
    gross_pay: Decimal
    cpf_employee: Decimal
    cpf_employer: Decimal
    net_pay: Decimal
    notes: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class PaySlipAdjust(BaseModel):
    allowances: Optional[Decimal] = None
    deductions: Optional[Decimal] = None
    overtime_hours: Optional[Decimal] = None
    overtime_pay: Optional[Decimal] = None
    notes: Optional[str] = None


# Needed for forward reference resolution
PayrollRunRead.model_rebuild()


# ---------- Commission ----------


class CommissionTier(BaseModel):
    min: Decimal = Field(..., ge=0, description="Minimum sales amount for this tier")
    max: Optional[Decimal] = Field(None, ge=0, description="Maximum sales amount (null = unlimited)")
    rate: Decimal = Field(..., ge=0, le=1, description="Commission rate as decimal (e.g. 0.05 = 5%)")


class CommissionRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    tiers: list[CommissionTier] = Field(..., min_length=1)
    is_active: bool = True


class CommissionRuleRead(UUIDMixin):
    store_id: UUID
    name: str
    tiers: list[CommissionTier]
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("tiers", mode="before")
    @classmethod
    def parse_tiers_json(cls, v):
        if isinstance(v, str):
            import json
            return json.loads(v)
        return v


class CommissionRuleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    tiers: Optional[list[CommissionTier]] = None
    is_active: Optional[bool] = None


class CommissionEntryRead(UUIDMixin):
    payslip_id: UUID
    commission_rule_id: Optional[UUID] = None
    sales_amount: Decimal
    commission_amount: Decimal
    rule_name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
