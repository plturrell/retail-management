import math
import uuid as _uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from google.cloud.firestore_v1.client import Client as FirestoreClient
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

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
    require_store_role,
    require_store_access,
)
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _col_path(store_id: UUID) -> str:
    """Return the Firestore collection path for timesheets under a store."""
    return f"stores/{store_id}/timesheets"


def _user_id(user: object) -> str:
    if isinstance(user, dict):
        return str(user.get("id", ""))
    return str(getattr(user, "id", ""))


def _user_name(user: object) -> str:
    if isinstance(user, dict):
        return str(user.get("full_name", ""))
    return str(getattr(user, "full_name", ""))


def _user_store_roles(user: object) -> list:
    if isinstance(user, dict):
        return list(user.get("store_roles", []))
    return list(getattr(user, "store_roles", []))


def _store_role_store_id(store_role: object) -> UUID | None:
    raw = store_role.get("store_id") if isinstance(store_role, dict) else getattr(store_role, "store_id", None)
    if raw is None:
        return None
    return raw if isinstance(raw, UUID) else UUID(str(raw))


def _entry_clock_in(entry: dict) -> datetime | None:
    value = entry.get("clock_in")
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _open_entries_for_user(entries: list[dict], user_id: str) -> list[dict]:
    return [
        entry for entry in entries
        if entry.get("user_id") == user_id and entry.get("clock_out") is None
    ]


def _entry_to_read(data: dict) -> TimeEntryRead:
    """Convert a Firestore timesheet dict to a TimeEntryRead schema."""
    return TimeEntryRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        user_id=UUID(data["user_id"]) if isinstance(data.get("user_id"), str) else data.get("user_id"),
        store_id=UUID(data["store_id"]) if isinstance(data.get("store_id"), str) else data.get("store_id"),
        clock_in=data.get("clock_in"),
        clock_out=data.get("clock_out"),
        break_minutes=data.get("break_minutes", 0),
        notes=data.get("notes"),
        status=data.get("status", "pending"),
        approved_by=(
            UUID(data["approved_by"]) if isinstance(data.get("approved_by"), str) else data.get("approved_by")
        ),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
        updated_at=data.get("updated_at"),
    )


# ===================== Clock In / Out =====================


@router.post("/api/timesheets/clock-in", response_model=DataResponse[TimeEntryRead], status_code=201)
async def clock_in(
    payload: ClockInRequest,
    user=Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    # Check if already clocked in (open entry with no clock_out)
    col = _col_path(payload.store_id)
    user_id = _user_id(user)
    open_entries = _open_entries_for_user(query_collection(col, order_by="-clock_in"), user_id)
    if open_entries:
        raise HTTPException(status_code=400, detail="Already clocked in")

    now = datetime.now(timezone.utc)
    doc_id = str(_uuid.uuid4())
    entry_data = {
        "user_id": user_id,
        "store_id": str(payload.store_id),
        "clock_in": now,
        "clock_out": None,
        "break_minutes": 0,
        "notes": payload.notes,
        "status": "pending",
        "approved_by": None,
        "user_name": _user_name(user),
        "created_at": now,
        "updated_at": now,
    }
    result = create_document(col, entry_data, doc_id=doc_id)
    return DataResponse(data=_entry_to_read(result))


@router.post("/api/timesheets/clock-out", response_model=DataResponse[TimeEntryRead])
async def clock_out(
    payload: ClockOutRequest,
    user=Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    # Find all stores the user might be clocked into — check each store's timesheets
    # We need to find the open entry. Query all stores' timesheets for this user.
    # Since timesheets are per-store, iterate user's store roles.
    open_entry = None
    entry_col = None
    user_id = _user_id(user)
    for sr in _user_store_roles(user):
        store_id = _store_role_store_id(sr)
        if store_id is None:
            continue
        col = _col_path(store_id)
        entries = _open_entries_for_user(query_collection(col, order_by="-clock_in"), user_id)
        if entries:
            open_entry = entries[0]
            entry_col = col
            break

    if open_entry is None:
        raise HTTPException(status_code=400, detail="Not currently clocked in")

    now = datetime.now(timezone.utc)
    update_data = {
        "clock_out": now,
        "break_minutes": payload.break_minutes,
        "updated_at": now,
    }
    if payload.notes is not None:
        update_data["notes"] = payload.notes

    updated = update_document(entry_col, open_entry["id"], update_data)
    return DataResponse(data=_entry_to_read(updated))


@router.get("/api/timesheets/status", response_model=DataResponse[Optional[TimeEntryRead]])
async def clock_status(
    user=Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    # Search across user's stores for an open entry
    user_id = _user_id(user)
    for sr in _user_store_roles(user):
        store_id = _store_role_store_id(sr)
        if store_id is None:
            continue
        col = _col_path(store_id)
        entries = _open_entries_for_user(query_collection(col, order_by="-clock_in"), user_id)
        if entries:
            return DataResponse(data=_entry_to_read(entries[0]))
    return DataResponse(data=None)


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
    _=Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    col = _col_path(store_id)
    all_items = query_collection(col, order_by="-clock_in")
    if user_id is not None:
        all_items = [item for item in all_items if item.get("user_id") == str(user_id)]
    if date_from is not None:
        date_from_utc = date_from if date_from.tzinfo else date_from.replace(tzinfo=timezone.utc)
        all_items = [
            item for item in all_items
            if (clock_in := _entry_clock_in(item)) is not None and clock_in >= date_from_utc
        ]
    if date_to is not None:
        date_to_utc = date_to if date_to.tzinfo else date_to.replace(tzinfo=timezone.utc)
        all_items = [
            item for item in all_items
            if (clock_in := _entry_clock_in(item)) is not None and clock_in <= date_to_utc
        ]
    if status is not None:
        all_items = [item for item in all_items if item.get("status") == status]

    total = len(all_items)

    offset = (page - 1) * page_size
    page_items = all_items[offset : offset + page_size]

    return PaginatedResponse(
        data=[_entry_to_read(i) for i in page_items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/api/stores/{store_id}/timesheets/summary", response_model=DataResponse[TimesheetSummaryResponse])
async def timesheet_summary(
    store_id: UUID,
    date_from: datetime,
    date_to: datetime,
    _=Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    col = _col_path(store_id)
    date_from_utc = date_from if date_from.tzinfo else date_from.replace(tzinfo=timezone.utc)
    date_to_utc = date_to if date_to.tzinfo else date_to.replace(tzinfo=timezone.utc)
    entries_data = [
        entry for entry in query_collection(col, order_by="clock_in")
        if (clock_in := _entry_clock_in(entry)) is not None and date_from_utc <= clock_in <= date_to_utc
    ]

    # Group by user
    user_entries: dict[str, list] = {}
    user_names: dict[str, str] = {}
    for entry in entries_data:
        uid = entry.get("user_id", "")
        if uid not in user_entries:
            user_entries[uid] = []
            user_names[uid] = entry.get("user_name", "Unknown")
        user_entries[uid].append(entry)

    summaries = []
    for uid, uentries in user_entries.items():
        validated = [_entry_to_read(e) for e in uentries]
        total_hours = sum(e.hours_worked or 0 for e in validated)
        unique_days = len(set(e.clock_in.date() for e in validated))
        summaries.append(
            TimesheetSummaryEntry(
                user_id=UUID(uid) if isinstance(uid, str) else uid,
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
    _=Depends(require_store_role(RoleEnum.manager)),
    user=Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    col = _col_path(store_id)
    entry = get_document(col, str(entry_id))
    if entry is None:
        raise HTTPException(status_code=404, detail="Time entry not found")

    update_data = payload.model_dump(exclude_unset=True)

    # Convert UUID values to strings for Firestore
    for key in ("clock_out",):
        pass  # datetime is fine as-is

    # If status is being changed to approved/rejected, record approver
    if "status" in update_data:
        update_data["approved_by"] = _user_id(user)

    update_data["updated_at"] = datetime.now(timezone.utc)
    updated = update_document(col, str(entry_id), update_data)
    return DataResponse(data=_entry_to_read(updated))


@router.delete("/api/stores/{store_id}/timesheets/{entry_id}", status_code=204)
async def delete_timesheet(
    store_id: UUID,
    entry_id: UUID,
    _=Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    col = _col_path(store_id)
    entry = get_document(col, str(entry_id))
    if entry is None:
        raise HTTPException(status_code=404, detail="Time entry not found")
    delete_document(col, str(entry_id))


# ===================== Timesheet Import =====================


@router.post(
    "/api/stores/{store_id}/timesheets/import",
    response_model=DataResponse[TimesheetImportReport],
)
async def import_timesheets(
    store_id: UUID,
    file: UploadFile = File(...),
    _=Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Import legacy timesheet data from a CSV or Excel file."""
    content = await file.read()
    filename = file.filename or "upload.csv"
    import_result = import_timesheet_file(db, store_id, filename, content)
    report = TimesheetImportReport(**import_result.to_dict())
    return DataResponse(data=report)


@router.post(
    "/api/stores/{store_id}/timesheets/import-ve-payroll",
    response_model=DataResponse[VEPayrollImportReport],
)
async def import_ve_payroll_endpoint(
    store_id: UUID,
    file: UploadFile = File(...),
    _=Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Import Victoria Enso legacy payroll Excel file.

    Expects a multi-sheet .xlsx workbook where each sheet is one month.
    Auto-detects staff columns from 'Person: XXX' cells, extracts daily
    hours and sales, creates TimeEntry and Order records.
    """
    content = await file.read()
    import_result = import_ve_payroll(db, store_id, content)
    report = VEPayrollImportReport(**import_result.to_dict())
    return DataResponse(data=report)
