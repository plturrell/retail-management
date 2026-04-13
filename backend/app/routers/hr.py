"""Human Resources and Shift Management endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.user import RoleEnum as _RoleEnum, User, UserStoreRole
from app.models.payroll import EmployeeProfile
from app.models.timesheet import TimeEntry, TimeEntryStatus
from app.auth.dependencies import get_current_user, ensure_store_role, require_store_role

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
    user_id: UUID  # In production, derived securely, but required if manager clocks in a staff member
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch all active employees associated with this specific store."""
    ensure_store_role(current_user, store_id, _RoleEnum.manager)
    query = (
        select(UserStoreRole)
        .options(selectinload(UserStoreRole.user))
        .where(UserStoreRole.store_id == store_id)
    )
    result = await db.execute(query)
    roles = result.scalars().all()
    
    # Normally we query EmployeeProfile directly, but for now we fallback correctly to mapped structural definitions
    mapped_employees = []
    for role in roles:
        mapped_employees.append(
            EmployeeRead(
                id=role.user.id, # Map fallback for ID abstractions
                user_id=role.user.id,
                full_name=role.user.full_name,
                email=role.user.email,
                role=role.role.value,
                is_active=True
            )
        )
    return mapped_employees


@router.post("/clock-in", response_model=TimeEntryRead)
async def clock_in_staff(
    store_id: UUID,
    req: ClockActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generates a fresh active shift entity. Errors if already clocked in."""
    # Authorise: user can clock themselves in, or a manager can clock in staff
    if req.user_id != current_user.id:
        ensure_store_role(current_user, store_id, _RoleEnum.manager)

    # Verify target user belongs to this store
    target_role = await db.execute(
        select(UserStoreRole).where(
            UserStoreRole.user_id == req.user_id,
            UserStoreRole.store_id == store_id,
        )
    )
    if target_role.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Target user does not belong to this store",
        )

    # Check if active shift exists
    active_q = select(TimeEntry).where(
        TimeEntry.user_id == req.user_id,
        TimeEntry.store_id == store_id,
        TimeEntry.clock_out.is_(None)
    )
    result = await db.execute(active_q)
    active = result.scalar_one_or_none()
    
    if active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already clocked in and hasn't closed out the active roster shift."
        )

    now = datetime.now(timezone.utc)
    new_entry = TimeEntry(
        user_id=req.user_id,
        store_id=store_id,
        clock_in=now,
        status=TimeEntryStatus.pending,
        notes=req.notes
    )
    
    db.add(new_entry)
    await db.flush()
    await db.refresh(new_entry)
    
    return new_entry


@router.post("/clock-out", response_model=TimeEntryRead)
async def clock_out_staff(
    store_id: UUID,
    req: ClockActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Closes an active running shift. Errors if no active shift."""
    # Authorise: user can clock themselves out, or a manager can clock out staff
    if req.user_id != current_user.id:
        ensure_store_role(current_user, store_id, _RoleEnum.manager)

    # Verify target user belongs to this store
    target_role = await db.execute(
        select(UserStoreRole).where(
            UserStoreRole.user_id == req.user_id,
            UserStoreRole.store_id == store_id,
        )
    )
    if target_role.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Target user does not belong to this store",
        )

    active_q = select(TimeEntry).where(
        TimeEntry.user_id == req.user_id,
        TimeEntry.store_id == store_id,
        TimeEntry.clock_out.is_(None)
    )
    result = await db.execute(active_q)
    active_entry = result.scalar_one_or_none()
    
    if not active_entry:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot clock out. No active shift is currently tracking for this identity."
        )

    active_entry.clock_out = datetime.now(timezone.utc)
    if req.notes:
        active_entry.notes = req.notes

    await db.flush()
    await db.refresh(active_entry)
    
    return active_entry
