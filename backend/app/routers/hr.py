"""Human Resources and Shift Management endpoints."""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from google.cloud.firestore_v1.client import Client as FirestoreClient

from app.firestore import get_firestore_db
from app.firestore_helpers import (
    create_document,
    get_document,
    query_collection,
    update_document,
)
from app.auth.dependencies import (
    RoleEnum as _RoleEnum,
    ensure_store_role,
    get_current_user,
    require_store_role,
)

router = APIRouter(prefix="/api/stores/{store_id}/hr", tags=["hr"])


class EmployeeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    full_name: str
    email: str
    role: str
    is_active: bool


class ClockActionRequest(BaseModel):
    user_id: UUID
    notes: Optional[str] = None


class TimeEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    store_id: UUID
    clock_in: datetime
    clock_out: Optional[datetime]
    break_minutes: int
    status: str


@router.get("/employees", response_model=List[EmployeeRead])
async def get_store_employees(
    store_id: UUID,
    db: FirestoreClient = Depends(get_firestore_db),
    current_user: dict = Depends(get_current_user),
):
    """Fetch all active employees associated with this specific store."""
    ensure_store_role(current_user, store_id, _RoleEnum.manager)

    role_path = f"stores/{store_id}/roles"
    role_docs = query_collection(role_path)

    mapped_employees: List[EmployeeRead] = []
    for role in role_docs:
        uid = role.get("user_id", role.get("id"))
        user_data = get_document("users", str(uid))
        if user_data is None:
            continue
        role_val = role.get("role", "staff")
        if hasattr(role_val, "value"):
            role_val = role_val.value
        mapped_employees.append(
            EmployeeRead(
                id=UUID(user_data["id"]) if isinstance(user_data.get("id"), str) else user_data.get("id"),
                user_id=UUID(user_data["id"]) if isinstance(user_data.get("id"), str) else user_data.get("id"),
                full_name=user_data.get("full_name", ""),
                email=user_data.get("email", ""),
                role=role_val,
                is_active=True,
            )
        )
    return mapped_employees


@router.post("/clock-in", response_model=TimeEntryRead)
async def clock_in_staff(
    store_id: UUID,
    req: ClockActionRequest,
    db: FirestoreClient = Depends(get_firestore_db),
    current_user: dict = Depends(get_current_user),
):
    """Generates a fresh active shift entity. Errors if already clocked in."""
    if str(req.user_id) != str(current_user.get("id")):
        ensure_store_role(current_user, store_id, _RoleEnum.manager)

    # Verify target user belongs to this store
    role_path = f"stores/{store_id}/roles"
    target_role = get_document(role_path, str(req.user_id))
    if target_role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Target user does not belong to this store",
        )

    # Check if active shift exists (timesheets subcollection)
    ts_path = f"stores/{store_id}/timesheets"
    active_shifts = query_collection(
        ts_path,
        filters=[
            ("user_id", "==", str(req.user_id)),
            ("clock_out", "==", None),
        ],
        limit=1,
    )

    if active_shifts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already clocked in and hasn't closed out the active roster shift.",
        )

    now = datetime.now(timezone.utc)
    entry_id = str(_uuid.uuid4())
    entry_data = {
        "id": entry_id,
        "user_id": str(req.user_id),
        "store_id": str(store_id),
        "clock_in": now,
        "clock_out": None,
        "break_minutes": 0,
        "status": "pending",
        "notes": req.notes,
    }

    create_document(ts_path, entry_data, doc_id=entry_id)

    return TimeEntryRead(
        id=UUID(entry_id),
        user_id=req.user_id,
        store_id=store_id,
        clock_in=now,
        clock_out=None,
        break_minutes=0,
        status="pending",
    )


@router.post("/clock-out", response_model=TimeEntryRead)
async def clock_out_staff(
    store_id: UUID,
    req: ClockActionRequest,
    db: FirestoreClient = Depends(get_firestore_db),
    current_user: dict = Depends(get_current_user),
):
    """Closes an active running shift. Errors if no active shift."""
    if str(req.user_id) != str(current_user.get("id")):
        ensure_store_role(current_user, store_id, _RoleEnum.manager)

    # Verify target user belongs to this store
    role_path = f"stores/{store_id}/roles"
    target_role = get_document(role_path, str(req.user_id))
    if target_role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Target user does not belong to this store",
        )

    ts_path = f"stores/{store_id}/timesheets"
    active_shifts = query_collection(
        ts_path,
        filters=[
            ("user_id", "==", str(req.user_id)),
            ("clock_out", "==", None),
        ],
        limit=1,
    )

    if not active_shifts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot clock out. No active shift is currently tracking for this identity.",
        )

    active_entry = active_shifts[0]
    now = datetime.now(timezone.utc)
    updates = {"clock_out": now}
    if req.notes:
        updates["notes"] = req.notes

    update_document(ts_path, active_entry["id"], updates)

    return TimeEntryRead(
        id=UUID(active_entry["id"]) if isinstance(active_entry.get("id"), str) else active_entry.get("id"),
        user_id=req.user_id,
        store_id=store_id,
        clock_in=active_entry.get("clock_in", now),
        clock_out=now,
        break_minutes=active_entry.get("break_minutes", 0),
        status=active_entry.get("status", "pending"),
    )
