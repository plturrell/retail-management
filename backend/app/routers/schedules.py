from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.schedule import Schedule, ScheduleStatusEnum, Shift
from app.models.user import RoleEnum, User, UserStoreRole
from app.auth.dependencies import get_current_user, require_store_access, require_store_role
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.schedule import (
    DayShifts,
    ScheduleCreate,
    ScheduleRead,
    ScheduleUpdate,
    ShiftCreate,
    ShiftRead,
    ShiftUpdate,
    WeeklyScheduleResponse,
)

router = APIRouter(prefix="/api/stores/{store_id}/schedules", tags=["schedules"])

STORE_OPEN = time(10, 0)
STORE_CLOSE = time(22, 0)


def _validate_shift_times(start_time: time, end_time: time) -> None:
    """Validate shift times are within store hours and end > start."""
    if end_time <= start_time:
        raise HTTPException(status_code=400, detail="end_time must be after start_time")
    if start_time < STORE_OPEN or end_time > STORE_CLOSE:
        raise HTTPException(
            status_code=400,
            detail=f"Shift times must be within store hours ({STORE_OPEN.strftime('%H:%M')}-{STORE_CLOSE.strftime('%H:%M')})",
        )


def _validate_shift_date_in_week(shift_date: date, week_start: date) -> None:
    """Validate that shift_date falls within the schedule's week (Mon-Sun)."""
    week_end = week_start + timedelta(days=6)
    if shift_date < week_start or shift_date > week_end:
        raise HTTPException(
            status_code=400,
            detail=f"shift_date must be within the schedule week ({week_start} to {week_end})",
        )


# ==================== Schedule CRUD ====================


@router.post("", response_model=DataResponse[ScheduleRead], status_code=201)
async def create_schedule(
    store_id: UUID,
    payload: ScheduleCreate,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if payload.store_id != store_id:
        raise HTTPException(status_code=400, detail="Payload store_id must match route store_id")

    # Validate week_start is a Monday
    if payload.week_start.weekday() != 0:
        raise HTTPException(status_code=400, detail="week_start must be a Monday")

    # Check for duplicate
    existing = await db.execute(
        select(Schedule).where(
            Schedule.store_id == store_id,
            Schedule.week_start == payload.week_start,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="A schedule already exists for this week",
        )

    schedule = Schedule(
        store_id=store_id,
        week_start=payload.week_start,
        status=ScheduleStatusEnum.draft,
        created_by=user.id,
    )
    db.add(schedule)
    await db.flush()
    await db.refresh(schedule)
    return DataResponse(data=ScheduleRead.model_validate(schedule))


@router.get("", response_model=PaginatedResponse[ScheduleRead])
async def list_schedules(
    store_id: UUID,
    page: int = 1,
    page_size: int = 10,
    week_start: date | None = None,
    status: str | None = None,
    _: UserStoreRole = Depends(require_store_access),
    db: AsyncSession = Depends(get_db),
):
    base = select(Schedule).where(Schedule.store_id == store_id)
    if week_start is not None:
        base = base.where(Schedule.week_start == week_start)
    if status is not None:
        base = base.where(Schedule.status == status)

    count_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = count_result.scalar() or 0

    query = base.order_by(Schedule.week_start.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()

    return PaginatedResponse(
        data=[ScheduleRead.model_validate(s) for s in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/my-shifts", response_model=DataResponse[list[ShiftRead]])
async def my_shifts(
    store_id: UUID,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    _: UserStoreRole = Depends(require_store_access),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Shift)
        .join(Schedule, Shift.schedule_id == Schedule.id)
        .where(
            Schedule.store_id == store_id,
            Shift.user_id == user.id,
            Shift.shift_date >= from_date,
            Shift.shift_date <= to_date,
        )
        .order_by(Shift.shift_date, Shift.start_time)
    )
    result = await db.execute(query)
    shifts = result.scalars().all()
    return DataResponse(data=[ShiftRead.model_validate(s) for s in shifts])


@router.get("/{schedule_id}", response_model=DataResponse[WeeklyScheduleResponse])
async def get_schedule(
    store_id: UUID,
    schedule_id: UUID,
    _: UserStoreRole = Depends(require_store_access),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Schedule).where(
            Schedule.id == schedule_id, Schedule.store_id == store_id
        )
    )
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    schedule_read = ScheduleRead.model_validate(schedule)

    # Group shifts by date
    shifts_by_date: dict[date, list[ShiftRead]] = {}
    for shift in schedule_read.shifts:
        shifts_by_date.setdefault(shift.shift_date, []).append(shift)

    days = [
        DayShifts(date=d, shifts=shifts_by_date.get(d, []))
        for d in sorted(shifts_by_date.keys())
    ]

    return DataResponse(
        data=WeeklyScheduleResponse(schedule=schedule_read, days=days)
    )


@router.patch("/{schedule_id}", response_model=DataResponse[ScheduleRead])
async def update_schedule(
    store_id: UUID,
    schedule_id: UUID,
    payload: ScheduleUpdate,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Schedule).where(
            Schedule.id == schedule_id, Schedule.store_id == store_id
        )
    )
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    if payload.status is not None:
        if payload.status == "published":
            schedule.status = ScheduleStatusEnum.published
            schedule.published_at = datetime.now(timezone.utc)
        elif payload.status == "draft":
            schedule.status = ScheduleStatusEnum.draft
            schedule.published_at = None
        else:
            raise HTTPException(status_code=400, detail="Invalid status value")

    await db.flush()
    await db.refresh(schedule)
    return DataResponse(data=ScheduleRead.model_validate(schedule))


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(
    store_id: UUID,
    schedule_id: UUID,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Schedule).where(
            Schedule.id == schedule_id, Schedule.store_id == store_id
        )
    )
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    if schedule.status == ScheduleStatusEnum.published:
        raise HTTPException(
            status_code=400, detail="Cannot delete a published schedule"
        )

    await db.delete(schedule)


# ==================== Shift CRUD ====================


@router.post(
    "/{schedule_id}/shifts",
    response_model=DataResponse[ShiftRead],
    status_code=201,
)
async def add_shift(
    store_id: UUID,
    schedule_id: UUID,
    payload: ShiftCreate,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Schedule).where(
            Schedule.id == schedule_id, Schedule.store_id == store_id
        )
    )
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    assignee_result = await db.execute(
        select(UserStoreRole).where(
            UserStoreRole.user_id == payload.user_id,
            UserStoreRole.store_id == store_id,
        )
    )
    if assignee_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=400, detail="Shift user does not belong to this store")

    _validate_shift_times(payload.start_time, payload.end_time)
    _validate_shift_date_in_week(payload.shift_date, schedule.week_start)

    shift = Shift(
        schedule_id=schedule_id,
        user_id=payload.user_id,
        shift_date=payload.shift_date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        break_minutes=payload.break_minutes,
        notes=payload.notes,
    )
    db.add(shift)
    await db.flush()
    await db.refresh(shift)
    return DataResponse(data=ShiftRead.model_validate(shift))


@router.patch(
    "/{schedule_id}/shifts/{shift_id}",
    response_model=DataResponse[ShiftRead],
)
async def update_shift(
    store_id: UUID,
    schedule_id: UUID,
    shift_id: UUID,
    payload: ShiftUpdate,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Shift)
        .join(Schedule, Shift.schedule_id == Schedule.id)
        .where(
            Shift.id == shift_id,
            Shift.schedule_id == schedule_id,
            Schedule.store_id == store_id,
        )
    )
    shift = result.scalar_one_or_none()
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found")

    updates = payload.model_dump(exclude_unset=True)

    if "user_id" in updates and updates["user_id"] is not None:
        assignee_result = await db.execute(
            select(UserStoreRole).where(
                UserStoreRole.user_id == updates["user_id"],
                UserStoreRole.store_id == store_id,
            )
        )
        if assignee_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail="Shift user does not belong to this store")

    # Apply updates
    for key, value in updates.items():
        setattr(shift, key, value)

    # Validate times after update
    _validate_shift_times(shift.start_time, shift.end_time)

    # Validate date if changed — need schedule's week_start
    sched_result = await db.execute(
        select(Schedule).where(
            Schedule.id == schedule_id,
            Schedule.store_id == store_id,
        )
    )
    schedule = sched_result.scalar_one()
    _validate_shift_date_in_week(shift.shift_date, schedule.week_start)

    await db.flush()
    await db.refresh(shift)
    return DataResponse(data=ShiftRead.model_validate(shift))


@router.delete("/{schedule_id}/shifts/{shift_id}", status_code=204)
async def delete_shift(
    store_id: UUID,
    schedule_id: UUID,
    shift_id: UUID,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Shift)
        .join(Schedule, Shift.schedule_id == Schedule.id)
        .where(
            Shift.id == shift_id,
            Shift.schedule_id == schedule_id,
            Schedule.store_id == store_id,
        )
    )
    shift = result.scalar_one_or_none()
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found")
    await db.delete(shift)
