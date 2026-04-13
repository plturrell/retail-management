import enum
import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._mixins import uuid_pk, created_at_col, updated_at_col


class LevelEnum(str, enum.Enum):
    entry = "entry"
    junior = "junior"
    senior = "senior"
    lead = "lead"
    manager = "manager"
    director = "director"


class LeaveStatusEnum(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[uuid_pk]
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Null store_id means company-wide department
    store_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    store = relationship("Store", lazy="raise")
    positions = relationship("JobPosition", back_populates="department", lazy="raise")

    def __repr__(self) -> str:
        return f"<Department {self.code}: {self.name}>"


class JobPosition(Base):
    __tablename__ = "job_positions"

    id: Mapped[uuid_pk]
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id"), nullable=False
    )
    level: Mapped[LevelEnum] = mapped_column(
        SQLEnum(LevelEnum, name="position_level_enum"),
        default=LevelEnum.entry,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    department = relationship("Department", back_populates="positions", lazy="raise")

    def __repr__(self) -> str:
        return f"<JobPosition {self.code}: {self.title}>"


class LeaveType(Base):
    __tablename__ = "leave_types"

    id: Mapped[uuid_pk]
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    days_per_year: Mapped[float] = mapped_column(Numeric(5, 1), nullable=False)
    carry_over_days: Mapped[float] = mapped_column(
        Numeric(5, 1), default=0, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    requests = relationship("LeaveRequest", back_populates="leave_type", lazy="raise")
    balances = relationship("LeaveBalance", back_populates="leave_type", lazy="raise")

    def __repr__(self) -> str:
        return f"<LeaveType {self.code}: {self.name} paid={self.is_paid}>"


class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    id: Mapped[uuid_pk]
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    leave_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leave_types.id"), nullable=False
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    days_requested: Mapped[float] = mapped_column(Numeric(5, 1), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    status: Mapped[LeaveStatusEnum] = mapped_column(
        SQLEnum(LeaveStatusEnum, name="leave_status_enum"),
        default=LeaveStatusEnum.pending,
        nullable=False,
    )
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    user = relationship(
        "User", foreign_keys=[user_id], lazy="raise"
    )
    approver = relationship(
        "User", foreign_keys=[approved_by], lazy="raise"
    )
    leave_type = relationship("LeaveType", back_populates="requests", lazy="raise")

    def __repr__(self) -> str:
        return f"<LeaveRequest user={self.user_id} type={self.leave_type_id} status={self.status}>"


class LeaveBalance(Base):
    """Tracks annual leave entitlement and usage per employee per leave type."""

    __tablename__ = "leave_balances"
    __table_args__ = (
        UniqueConstraint("user_id", "leave_type_id", "year", name="uq_leave_balance"),
    )

    id: Mapped[uuid_pk]
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    leave_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leave_types.id"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    entitled_days: Mapped[float] = mapped_column(Numeric(5, 1), nullable=False)
    used_days: Mapped[float] = mapped_column(Numeric(5, 1), default=0, nullable=False)
    pending_days: Mapped[float] = mapped_column(Numeric(5, 1), default=0, nullable=False)
    carried_over_days: Mapped[float] = mapped_column(
        Numeric(5, 1), default=0, nullable=False
    )
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    @property
    def remaining_days(self) -> float:
        return float(self.entitled_days) + float(self.carried_over_days) - float(self.used_days) - float(self.pending_days)

    # Relationships
    user = relationship("User", lazy="raise")
    leave_type = relationship("LeaveType", back_populates="balances", lazy="raise")

    def __repr__(self) -> str:
        return f"<LeaveBalance user={self.user_id} type={self.leave_type_id} year={self.year} remaining={self.remaining_days}>"
