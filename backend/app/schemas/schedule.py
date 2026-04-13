from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import TimestampMixin, UUIDMixin


# ---------- Shift ----------

class ShiftCreate(BaseModel):
    user_id: UUID
    shift_date: date
    start_time: time
    end_time: time
    break_minutes: int = 60
    notes: str | None = Field(None, max_length=500)


class ShiftUpdate(BaseModel):
    user_id: UUID | None = None
    shift_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    break_minutes: int | None = None
    notes: str | None = Field(None, max_length=500)


class ShiftRead(UUIDMixin, TimestampMixin):
    schedule_id: UUID
    user_id: UUID
    shift_date: date
    start_time: time
    end_time: time
    break_minutes: int
    notes: str | None = None
    hours: float = 0.0

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def compute_hours(cls, values):
        """Compute worked hours = (end - start) - break."""
        if hasattr(values, "start_time"):
            # ORM object
            st = values.start_time
            et = values.end_time
            brk = values.break_minutes
        elif isinstance(values, dict):
            st = values.get("start_time")
            et = values.get("end_time")
            brk = values.get("break_minutes", 60)
        else:
            return values

        if st is not None and et is not None:
            start_dt = datetime.combine(date.today(), st)
            end_dt = datetime.combine(date.today(), et)
            diff = (end_dt - start_dt).total_seconds() / 3600.0
            hrs = max(0.0, diff - (brk or 0) / 60.0)
            if hasattr(values, "__dict__"):
                # ORM model — we can't set attrs, so convert to dict
                d = {
                    "id": values.id,
                    "schedule_id": values.schedule_id,
                    "user_id": values.user_id,
                    "shift_date": values.shift_date,
                    "start_time": values.start_time,
                    "end_time": values.end_time,
                    "break_minutes": values.break_minutes,
                    "notes": values.notes,
                    "created_at": values.created_at,
                    "updated_at": values.updated_at,
                    "hours": round(hrs, 2),
                }
                return d
            else:
                values["hours"] = round(hrs, 2)
        return values


# ---------- Schedule ----------

class ScheduleCreate(BaseModel):
    store_id: UUID
    week_start: date


class ScheduleUpdate(BaseModel):
    status: str | None = None


class ScheduleRead(UUIDMixin, TimestampMixin):
    store_id: UUID
    week_start: date
    status: str
    created_by: UUID
    published_at: datetime | None = None
    shifts: list[ShiftRead] = []

    model_config = ConfigDict(from_attributes=True)


# ---------- Weekly grouped response ----------

class DayShifts(BaseModel):
    date: date
    shifts: list[ShiftRead]


class WeeklyScheduleResponse(BaseModel):
    schedule: ScheduleRead
    days: list[DayShifts]
