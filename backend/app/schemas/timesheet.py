from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.schemas.common import TimestampMixin, UUIDMixin


# ---------- Clock In / Clock Out Requests ----------

class ClockInRequest(BaseModel):
    store_id: UUID
    notes: Optional[str] = None


class ClockOutRequest(BaseModel):
    break_minutes: int = 0
    notes: Optional[str] = None


# ---------- TimeEntry CRUD ----------

class TimeEntryCreate(BaseModel):
    store_id: UUID
    notes: Optional[str] = None


class TimeEntryUpdate(BaseModel):
    clock_out: Optional[datetime] = None
    break_minutes: Optional[int] = None
    notes: Optional[str] = None
    status: Optional[str] = None


class TimeEntryRead(UUIDMixin, TimestampMixin):
    user_id: UUID
    store_id: UUID
    clock_in: datetime
    clock_out: Optional[datetime] = None
    break_minutes: int = 0
    notes: Optional[str] = None
    status: str
    approved_by: Optional[UUID] = None

    @computed_field
    @property
    def hours_worked(self) -> Optional[float]:
        if self.clock_out is None:
            return None
        delta = (self.clock_out - self.clock_in).total_seconds()
        hours = (delta / 3600) - (self.break_minutes / 60)
        return round(max(hours, 0), 2)

    model_config = ConfigDict(from_attributes=True)


# ---------- Summary ----------

class TimesheetSummaryEntry(BaseModel):
    user_id: UUID
    full_name: str
    total_hours: float
    total_days: int
    entries: list[TimeEntryRead]


class TimesheetSummaryResponse(BaseModel):
    period_start: datetime
    period_end: datetime
    summaries: list[TimesheetSummaryEntry]
