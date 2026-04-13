from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy import and_, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.timesheet import TimeEntry, TimeEntryStatus
from app.models.user import RoleEnum, User, UserStoreRole
from app.auth.dependencies import get_current_user, require_store_role
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.timesheet import (
    ClockInRequest,
    ClockOutRequest,
    TimeEntryRead,
    TimeEntryUpdate,
    TimesheetImportReport,
    TimesheetSummaryEntry,
    TimesheetSummaryResponse,
    VEPayrollImportReport,
)
from app.services.timesheet_import import import_timesheet_file
from app.services.ve_payroll_import import import_ve_payroll

router = APIRouter(tags=["timesheets"])


# ===================== Clock In / Out =====================


@router.post("/api/timesheets/clock-in", response_model=DataResponse[TimeEntryRead], status_code=201)
async def clock_in(
    payload: ClockInRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Check if already clocked in (has an open entry with no clock_out)
    result = await db.execute(
        select(TimeEntry).where(
            TimeEntry.user_id == user.id,
            TimeEntry.clock_out.is_(None),
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=400, detail="Already clocked in")

    entry = TimeEntry(
        user_id=user.id,
        store_id=payload.store_id,
        clock_in=datetime.now(timezone.utc),
        notes=payload.notes,
        status=TimeEntryStatus.pending,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return DataResponse(data=TimeEntryRead.model_validate(entry))


@router.post("/api/timesheets/clock-out", response_model=DataResponse[TimeEntryRead])
async def clock_out(
    payload: ClockOutRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TimeEntry).where(
            TimeEntry.user_id == user.id,
            TimeEntry.clock_out.is_(None),
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=400, detail="Not currently clocked in")

    entry.clock_out = datetime.now(timezone.utc)
    entry.break_minutes = payload.break_minutes
    if payload.notes is not None:
        entry.notes = payload.notes

    await db.flush()
    await db.refresh(entry)
    return DataResponse(data=TimeEntryRead.model_validate(entry))


@router.get("/api/timesheets/status", response_model=DataResponse[Optional[TimeEntryRead]])
async def clock_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TimeEntry).where(
            TimeEntry.user_id == user.id,
            TimeEntry.clock_out.is_(None),
        )
    )
    entry = result.scalar_one_or_none()
    data = TimeEntryRead.model_validate(entry) if entry else None
    return DataResponse(data=data)


# ===================== Store-scoped Timesheet Management =====================


@router.get("/api/stores/{store_id}/timesheets", response_model=PaginatedResponse[TimeEntryRead])
async def list_timesheets(
    store_id: UUID,
    page: int = 1,
    page_size: int = 50,
    user_id: Optional[UUID] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    status: Optional[str] = None,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    base = select(TimeEntry).where(TimeEntry.store_id == store_id)

    if user_id is not None:
        base = base.where(TimeEntry.user_id == user_id)
    if date_from is not None:
        base = base.where(TimeEntry.clock_in >= date_from)
    if date_to is not None:
        base = base.where(TimeEntry.clock_in <= date_to)
    if status is not None:
        base = base.where(TimeEntry.status == status)

    count_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = count_result.scalar() or 0

    query = base.order_by(TimeEntry.clock_in.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()

    return PaginatedResponse(
        data=[TimeEntryRead.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/api/stores/{store_id}/timesheets/summary", response_model=DataResponse[TimesheetSummaryResponse])
async def timesheet_summary(
    store_id: UUID,
    date_from: datetime,
    date_to: datetime,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TimeEntry)
        .options(selectinload(TimeEntry.user))
        .where(
            TimeEntry.store_id == store_id,
            TimeEntry.clock_in >= date_from,
            TimeEntry.clock_in <= date_to,
        ).order_by(TimeEntry.clock_in)
    )
    entries = result.scalars().all()

    # Group by user
    user_entries: dict[UUID, list] = {}
    user_names: dict[UUID, str] = {}
    for entry in entries:
        uid = entry.user_id
        if uid not in user_entries:
            user_entries[uid] = []
            user_names[uid] = entry.user.full_name if entry.user else "Unknown"
        user_entries[uid].append(entry)

    summaries = []
    for uid, uentries in user_entries.items():
        validated = [TimeEntryRead.model_validate(e) for e in uentries]
        total_hours = sum(e.hours_worked or 0 for e in validated)
        unique_days = len(set(e.clock_in.date() for e in validated))
        summaries.append(
            TimesheetSummaryEntry(
                user_id=uid,
                full_name=user_names[uid],
                total_hours=round(total_hours, 2),
                total_days=unique_days,
                entries=validated,
            )
        )

    return DataResponse(
        data=TimesheetSummaryResponse(
            period_start=date_from,
            period_end=date_to,
            summaries=summaries,
        )
    )


@router.patch("/api/stores/{store_id}/timesheets/{entry_id}", response_model=DataResponse[TimeEntryRead])
async def update_timesheet(
    store_id: UUID,
    entry_id: UUID,
    payload: TimeEntryUpdate,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TimeEntry).where(
            TimeEntry.id == entry_id,
            TimeEntry.store_id == store_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Time entry not found")

    update_data = payload.model_dump(exclude_unset=True)

    # If status is being changed to approved/rejected, record approver
    if "status" in update_data:
        entry.approved_by = user.id

    for key, value in update_data.items():
        setattr(entry, key, value)

    await db.flush()
    await db.refresh(entry)
    return DataResponse(data=TimeEntryRead.model_validate(entry))


@router.delete("/api/stores/{store_id}/timesheets/{entry_id}", status_code=204)
async def delete_timesheet(
    store_id: UUID,
    entry_id: UUID,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TimeEntry).where(
            TimeEntry.id == entry_id,
            TimeEntry.store_id == store_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Time entry not found")
    await db.delete(entry)


# ===================== Timesheet Import =====================


@router.post(
    "/api/stores/{store_id}/timesheets/import",
    response_model=DataResponse[TimesheetImportReport],
)
async def import_timesheets(
    store_id: UUID,
    file: UploadFile = File(...),
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    """Import legacy timesheet data from a CSV or Excel file."""
    content = await file.read()
    filename = file.filename or "upload.csv"
    import_result = await import_timesheet_file(db, store_id, filename, content)
    report = TimesheetImportReport(**import_result.to_dict())
    return DataResponse(data=report)



@router.post(
    "/api/stores/{store_id}/timesheets/import-ve-payroll",
    response_model=DataResponse[VEPayrollImportReport],
)
async def import_ve_payroll_endpoint(
    store_id: UUID,
    file: UploadFile = File(...),
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    """Import Victoria Enso legacy payroll Excel file.

    Expects a multi-sheet .xlsx workbook where each sheet is one month.
    Auto-detects staff columns from 'Person: XXX' cells, extracts daily
    hours and sales, creates TimeEntry and Order records.
    """
    content = await file.read()
    import_result = await import_ve_payroll(db, store_id, content)
    report = VEPayrollImportReport(**import_result.to_dict())
    return DataResponse(data=report)