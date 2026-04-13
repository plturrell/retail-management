from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.staff import LevelEnum, LeaveStatusEnum
from app.schemas.common import TimestampMixin, UUIDMixin


# ---------- Department ----------

class DepartmentBase(BaseModel):
    code: str = Field(..., max_length=20)
    name: str = Field(..., max_length=255)
    store_id: UUID | None = None
    is_active: bool = True


class DepartmentCreate(DepartmentBase):
    pass


class DepartmentUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    store_id: UUID | None = None
    is_active: bool | None = None


class DepartmentRead(DepartmentBase, UUIDMixin, TimestampMixin):
    pass


# ---------- JobPosition ----------

class JobPositionBase(BaseModel):
    code: str = Field(..., max_length=20)
    title: str = Field(..., max_length=255)
    department_id: UUID
    level: LevelEnum = LevelEnum.entry
    is_active: bool = True


class JobPositionCreate(JobPositionBase):
    pass


class JobPositionUpdate(BaseModel):
    title: str | None = Field(None, max_length=255)
    department_id: UUID | None = None
    level: LevelEnum | None = None
    is_active: bool | None = None


class JobPositionRead(JobPositionBase, UUIDMixin, TimestampMixin):
    pass


# ---------- LeaveType ----------

class LeaveTypeBase(BaseModel):
    code: str = Field(..., max_length=20)
    name: str = Field(..., max_length=255)
    is_paid: bool = True
    days_per_year: float = Field(..., gt=0)
    carry_over_days: float = Field(0.0, ge=0)
    is_active: bool = True


class LeaveTypeCreate(LeaveTypeBase):
    pass


class LeaveTypeUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    is_paid: bool | None = None
    days_per_year: float | None = Field(None, gt=0)
    carry_over_days: float | None = Field(None, ge=0)
    is_active: bool | None = None


class LeaveTypeRead(LeaveTypeBase, UUIDMixin, TimestampMixin):
    pass


# ---------- LeaveRequest ----------

class LeaveRequestBase(BaseModel):
    leave_type_id: UUID
    start_date: date
    end_date: date
    days_requested: float = Field(..., gt=0)
    reason: str | None = Field(None, max_length=1000)


class LeaveRequestCreate(LeaveRequestBase):
    pass


class LeaveRequestUpdate(BaseModel):
    status: LeaveStatusEnum | None = None
    rejection_reason: str | None = Field(None, max_length=500)


class LeaveRequestRead(LeaveRequestBase, UUIDMixin, TimestampMixin):
    user_id: UUID
    status: LeaveStatusEnum
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    rejection_reason: str | None = None


# ---------- LeaveBalance ----------

class LeaveBalanceRead(UUIDMixin, TimestampMixin):
    user_id: UUID
    leave_type_id: UUID
    year: int
    entitled_days: float
    used_days: float
    pending_days: float
    carried_over_days: float
    remaining_days: float


class LeaveBalanceUpsert(BaseModel):
    user_id: UUID
    leave_type_id: UUID
    year: int
    entitled_days: float = Field(..., ge=0)
    carried_over_days: float = Field(0.0, ge=0)
