import enum
import uuid
from datetime import date
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    Enum,
    ForeignKey,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._mixins import uuid_pk, created_at_col, updated_at_col


class NationalityEnum(str, enum.Enum):
    citizen = "citizen"
    pr = "pr"
    foreigner = "foreigner"


class PayrollStatusEnum(str, enum.Enum):
    draft = "draft"
    calculated = "calculated"
    approved = "approved"
    paid = "paid"


class EmployeeProfile(Base):
    __tablename__ = "employee_profiles"

    id: Mapped[uuid_pk]
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    nationality: Mapped[NationalityEnum] = mapped_column(
        Enum(NationalityEnum, name="nationality_enum"), nullable=False
    )
    basic_salary: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    hourly_rate: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    bank_account: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    bank_name: Mapped[str] = mapped_column(
        String(100), default="OCBC", nullable=False
    )
    cpf_account_number: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    user = relationship("User", back_populates="employee_profile", lazy="raise")

    def __repr__(self) -> str:
        return f"<EmployeeProfile user_id={self.user_id}>"


class PayrollRun(Base):
    __tablename__ = "payroll_runs"

    id: Mapped[uuid_pk]
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[PayrollStatusEnum] = mapped_column(
        Enum(PayrollStatusEnum, name="payroll_status_enum"),
        default=PayrollStatusEnum.draft,
        nullable=False,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    total_gross: Mapped[float] = mapped_column(
        Numeric(12, 2), default=0, nullable=False
    )
    total_cpf_employee: Mapped[float] = mapped_column(
        Numeric(12, 2), default=0, nullable=False
    )
    total_cpf_employer: Mapped[float] = mapped_column(
        Numeric(12, 2), default=0, nullable=False
    )
    total_net: Mapped[float] = mapped_column(
        Numeric(12, 2), default=0, nullable=False
    )
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    payslips = relationship("PaySlip", back_populates="payroll_run", lazy="selectin")  # needed for PayrollRunRead

    def __repr__(self) -> str:
        return f"<PayrollRun {self.period_start} - {self.period_end}>"


class PaySlip(Base):
    __tablename__ = "payslips"

    id: Mapped[uuid_pk]
    payroll_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payroll_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    basic_salary: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    hours_worked: Mapped[Optional[float]] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    overtime_hours: Mapped[float] = mapped_column(
        Numeric(8, 2), default=0, nullable=False
    )
    overtime_pay: Mapped[float] = mapped_column(
        Numeric(10, 2), default=0, nullable=False
    )
    allowances: Mapped[float] = mapped_column(
        Numeric(10, 2), default=0, nullable=False
    )
    deductions: Mapped[float] = mapped_column(
        Numeric(10, 2), default=0, nullable=False
    )
    gross_pay: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    cpf_employee: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    cpf_employer: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    net_pay: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    payroll_run = relationship("PayrollRun", back_populates="payslips", lazy="raise")

    def __repr__(self) -> str:
        return f"<PaySlip user_id={self.user_id} gross={self.gross_pay}>"
