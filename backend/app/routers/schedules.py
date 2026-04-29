from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from google.cloud.firestore_v1.client import Client as FirestoreClient

from app.firestore import get_firestore_db
from app.firestore_helpers import (
    create_document,
    doc_to_dict,
    get_document,
    query_collection,
    update_document,
    delete_document,
)
from app.auth.dependencies import (
    RoleEnum,
    get_current_user,
    require_store_access,
    require_store_role,
)
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sched_col(store_id: UUID) -> str:
    return f"stores/{store_id}/schedules"


def _shift_col(store_id: UUID, schedule_id: UUID | str) -> str:
    return f"stores/{store_id}/schedules/{schedule_id}/shifts"


def _parse_date_field(val) -> date | None:
    """Parse a date from Firestore — may be date, datetime, or ISO string."""
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        return date.fromisoformat(val)
    return None


def _parse_time_field(val) -> time | None:
    """Parse a time from Firestore — may be time or ISO string."""
    if isinstance(val, time):
        return val
    if isinstance(val, str):
        return time.fromisoformat(val)
    return None


def _schedule_to_read(data: dict, shifts: list[dict] | None = None) -> ScheduleRead:
    """Convert a Firestore schedule dict to ScheduleRead."""
    shift_reads = []
    if shifts:
        for s in shifts:
            shift_reads.append(_shift_to_read(s, data["id"]))
    return ScheduleRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        store_id=UUID(data["store_id"]) if isinstance(data.get("store_id"), str) else data.get("store_id"),
        week_start=_parse_date_field(data.get("week_start")),
        status=data.get("status", "draft"),
        created_by=UUID(data["created_by"]) if isinstance(data.get("created_by"), str) else data.get("created_by"),
        published_at=data.get("published_at"),
        shifts=shift_reads,
        created_at=data.get("created_at", datetime.now(timezone.utc)),
        updated_at=data.get("updated_at"),
    )


def _shift_to_read(data: dict, schedule_id: str | UUID = None) -> ShiftRead:
    """Convert a Firestore shift dict to ShiftRead."""
    sid = schedule_id or data.get("schedule_id", "")
    return ShiftRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        schedule_id=UUID(str(sid)) if isinstance(sid, str) else sid,
        user_id=UUID(data["user_id"]) if isinstance(data.get("user_id"), str) else data.get("user_id"),
        shift_date=_parse_date_field(data.get("shift_date")),
        start_time=_parse_time_field(data.get("start_time")),
        end_time=_parse_time_field(data.get("end_time")),
        break_minutes=data.get("break_minutes", 60),
        notes=data.get("notes"),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
        updated_at=data.get("updated_at"),
    )


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
    _=Depends(require_store_role(RoleEnum.manager)),
    user=Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    if payload.store_id != store_id:
        raise HTTPException(status_code=400, detail="Payload store_id must match route store_id")

    if payload.week_start.weekday() != 0:
        raise HTTPException(status_code=400, detail="week_start must be a Monday")

    # Check for duplicate
    col = _sched_col(store_id)
    existing = query_collection(
        col,
        filters=[("week_start", "==", payload.week_start.isoformat())],
    )
    if existing:
        raise HTTPException(status_code=409, detail="A schedule already exists for this week")

    now = datetime.now(timezone.utc)
    doc_id = str(_uuid.uuid4())
    sched_data = {
        "store_id": str(store_id),
        "week_start": payload.week_start.isoformat(),
        "status": "draft",
        "created_by": str(user.id),
        "published_at": None,
        "created_at": now,
        "updated_at": now,
    }
    result = create_document(col, sched_data, doc_id=doc_id)
    return DataResponse(data=_schedule_to_read(result))


@router.get("", response_model=PaginatedResponse[ScheduleRead])
async def list_schedules(
    store_id: UUID,
    page: int = 1,
    page_size: int = 10,
    week_start: date | None = None,
    status: str | None = None,
    _=Depends(require_store_access),
    db: FirestoreClient = Depends(get_firestore_db),
):
    col = _sched_col(store_id)
    filters = []
    if week_start is not None:
        filters.append(("week_start", "==", week_start.isoformat()))
    if status is not None:
        filters.append(("status", "==", status))

    all_items = query_collection(col, filters=filters, order_by="-week_start")
    total = len(all_items)

    offset = (page - 1) * page_size
    page_items = all_items[offset : offset + page_size]

    return PaginatedResponse(
        data=[_schedule_to_read(s) for s in page_items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/my-shifts", response_model=DataResponse[list[ShiftRead]])
async def my_shifts(
    store_id: UUID,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    _=Depends(require_store_access),
    user=Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    # Get all schedules for this store, then query shifts subcollection
    col = _sched_col(store_id)
    schedules = query_collection(col)

    all_shifts: list[ShiftRead] = []
    for sched in schedules:
        shift_col = _shift_col(store_id, sched["id"])
        shifts = query_collection(
            shift_col,
            filters=[
                ("user_id", "==", str(user.id)),
                ("shift_date", ">=", from_date.isoformat()),
                ("shift_date", "<=", to_date.isoformat()),
            ],
            order_by="shift_date",
        )
        for s in shifts:
            all_shifts.append(_shift_to_read(s, sched["id"]))

    # Sort by date then start_time
    all_shifts.sort(key=lambda s: (s.shift_date, s.start_time))
    return DataResponse(data=all_shifts)


@router.get("/{schedule_id}", response_model=DataResponse[WeeklyScheduleResponse])
async def get_schedule(
    store_id: UUID,
    schedule_id: UUID,
    _=Depends(require_store_access),
    db: FirestoreClient = Depends(get_firestore_db),
):
    col = _sched_col(store_id)
    sched = get_document(col, str(schedule_id))
    if sched is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    # Fetch shifts subcollection
    shift_col = _shift_col(store_id, schedule_id)
    shifts = query_collection(shift_col, order_by="shift_date")

    schedule_read = _schedule_to_read(sched, shifts)

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
    _=Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    col = _sched_col(store_id)
    sched = get_document(col, str(schedule_id))
    if sched is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    update_data: dict = {"updated_at": datetime.now(timezone.utc)}

    if payload.status is not None:
        if payload.status == "published":
            update_data["status"] = "published"
            update_data["published_at"] = datetime.now(timezone.utc)
        elif payload.status == "draft":
            update_data["status"] = "draft"
            update_data["published_at"] = None
        else:
            raise HTTPException(status_code=400, detail="Invalid status value")

    updated = update_document(col, str(schedule_id), update_data)
    return DataResponse(data=_schedule_to_read(updated))


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(
    store_id: UUID,
    schedule_id: UUID,
    _=Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    col = _sched_col(store_id)
    sched = get_document(col, str(schedule_id))
    if sched is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    if sched.get("status") == "published":
        raise HTTPException(status_code=400, detail="Cannot delete a published schedule")

    # Delete shifts subcollection first
    shift_col = _shift_col(store_id, schedule_id)
    shifts = query_collection(shift_col)
    for s in shifts:
        delete_document(shift_col, s["id"])

    delete_document(col, str(schedule_id))


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
    _=Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    sched_col = _sched_col(store_id)
    sched = get_document(sched_col, str(schedule_id))
    if sched is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    # Validate user belongs to store by checking user_store_roles collection
    roles = query_collection(
        f"stores/{store_id}/user_roles",
        filters=[("user_id", "==", str(payload.user_id))],
        limit=1,
    )
    if not roles:
        raise HTTPException(status_code=400, detail="Shift user does not belong to this store")

    _validate_shift_times(payload.start_time, payload.end_time)
    week_start = _parse_date_field(sched.get("week_start"))
    _validate_shift_date_in_week(payload.shift_date, week_start)

    now = datetime.now(timezone.utc)
    doc_id = str(_uuid.uuid4())
    shift_col = _shift_col(store_id, schedule_id)
    shift_data = {
        "schedule_id": str(schedule_id),
        "user_id": str(payload.user_id),
        "shift_date": payload.shift_date.isoformat(),
        "start_time": payload.start_time.isoformat(),
        "end_time": payload.end_time.isoformat(),
        "break_minutes": payload.break_minutes,
        "notes": payload.notes,
        "created_at": now,
        "updated_at": now,
    }
    result = create_document(shift_col, shift_data, doc_id=doc_id)
    return DataResponse(data=_shift_to_read(result, schedule_id))


@router.patch(
    "/{schedule_id}/shifts/{shift_id}",
    response_model=DataResponse[ShiftRead],
)
async def update_shift(
    store_id: UUID,
    schedule_id: UUID,
    shift_id: UUID,
    payload: ShiftUpdate,
    _=Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    shift_col = _shift_col(store_id, schedule_id)
    shift = get_document(shift_col, str(shift_id))
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found")

    updates = payload.model_dump(exclude_unset=True)

    if "user_id" in updates and updates["user_id"] is not None:
        roles = query_collection(
            f"stores/{store_id}/user_roles",
            filters=[("user_id", "==", str(updates["user_id"]))],
            limit=1,
        )
        if not roles:
            raise HTTPException(status_code=400, detail="Shift user does not belong to this store")
        updates["user_id"] = str(updates["user_id"])

    # Serialize date/time fields
    if "shift_date" in updates and updates["shift_date"] is not None:
        updates["shift_date"] = updates["shift_date"].isoformat()
    if "start_time" in updates and updates["start_time"] is not None:
        updates["start_time"] = updates["start_time"].isoformat()
    if "end_time" in updates and updates["end_time"] is not None:
        updates["end_time"] = updates["end_time"].isoformat()

    updates["updated_at"] = datetime.now(timezone.utc)
    updated = update_document(shift_col, str(shift_id), updates)

    # Validate times after update
    st = _parse_time_field(updated.get("start_time"))
    et = _parse_time_field(updated.get("end_time"))
    _validate_shift_times(st, et)

    # Validate date in week
    sched_col = _sched_col(store_id)
    sched = get_document(sched_col, str(schedule_id))
    week_start = _parse_date_field(sched.get("week_start"))
    sd = _parse_date_field(updated.get("shift_date"))
    _validate_shift_date_in_week(sd, week_start)

    return DataResponse(data=_shift_to_read(updated, schedule_id))


@router.delete("/{schedule_id}/shifts/{shift_id}", status_code=204)
async def delete_shift(
    store_id: UUID,
    schedule_id: UUID,
    shift_id: UUID,
    _=Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    shift_col = _shift_col(store_id, schedule_id)
    shift = get_document(shift_col, str(shift_id))
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found")
    delete_document(shift_col, str(shift_id))
