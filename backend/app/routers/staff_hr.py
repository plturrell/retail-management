from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.staff import (
    Department,
    JobPosition,
    LeaveBalance,
    LeaveRequest,
    LeaveStatusEnum,
    LeaveType,
)
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.staff import (
    DepartmentCreate,
    DepartmentRead,
    DepartmentUpdate,
    JobPositionCreate,
    JobPositionRead,
    JobPositionUpdate,
    LeaveBalanceRead,
    LeaveBalanceUpsert,
    LeaveRequestCreate,
    LeaveRequestRead,
    LeaveRequestUpdate,
    LeaveTypeCreate,
    LeaveTypeRead,
    LeaveTypeUpdate,
)

router = APIRouter(prefix="/api", tags=["staff-hr"])

_dept_router = APIRouter(prefix="/departments")
_pos_router = APIRouter(prefix="/job-positions")
_ltype_router = APIRouter(prefix="/leave-types")
_lreq_router = APIRouter(prefix="/leave-requests")
_lbal_router = APIRouter(prefix="/leave-balances")


# ------------------------------------------------------------------ #
# Departments                                                         #
# ------------------------------------------------------------------ #

@_dept_router.get("", response_model=DataResponse[list[DepartmentRead]])
async def list_departments(
    is_active: bool | None = None,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Department)
    if is_active is not None:
        q = q.where(Department.is_active == is_active)
    result = await db.execute(q.order_by(Department.name))
    return DataResponse(data=[DepartmentRead.model_validate(d) for d in result.scalars().all()])


@_dept_router.post("", response_model=DataResponse[DepartmentRead], status_code=201)
async def create_department(
    payload: DepartmentCreate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    dept = Department(**payload.model_dump())
    db.add(dept)
    await db.flush()
    await db.refresh(dept)
    return DataResponse(data=DepartmentRead.model_validate(dept))


@_dept_router.patch("/{dept_id}", response_model=DataResponse[DepartmentRead])
async def update_department(
    dept_id: UUID,
    payload: DepartmentUpdate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Department).where(Department.id == dept_id))
    dept = result.scalar_one_or_none()
    if dept is None:
        raise HTTPException(status_code=404, detail="Department not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(dept, key, value)
    await db.flush()
    await db.refresh(dept)
    return DataResponse(data=DepartmentRead.model_validate(dept))


# ------------------------------------------------------------------ #
# Job Positions                                                       #
# ------------------------------------------------------------------ #

@_pos_router.get("", response_model=DataResponse[list[JobPositionRead]])
async def list_positions(
    department_id: UUID | None = None,
    is_active: bool | None = None,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(JobPosition)
    if department_id:
        q = q.where(JobPosition.department_id == department_id)
    if is_active is not None:
        q = q.where(JobPosition.is_active == is_active)
    result = await db.execute(q.order_by(JobPosition.title))
    return DataResponse(data=[JobPositionRead.model_validate(p) for p in result.scalars().all()])


@_pos_router.post("", response_model=DataResponse[JobPositionRead], status_code=201)
async def create_position(
    payload: JobPositionCreate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    position = JobPosition(**payload.model_dump())
    db.add(position)
    await db.flush()
    await db.refresh(position)
    return DataResponse(data=JobPositionRead.model_validate(position))


@_pos_router.patch("/{position_id}", response_model=DataResponse[JobPositionRead])
async def update_position(
    position_id: UUID,
    payload: JobPositionUpdate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(JobPosition).where(JobPosition.id == position_id))
    position = result.scalar_one_or_none()
    if position is None:
        raise HTTPException(status_code=404, detail="Job position not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(position, key, value)
    await db.flush()
    await db.refresh(position)
    return DataResponse(data=JobPositionRead.model_validate(position))


# ------------------------------------------------------------------ #
# Leave Types                                                         #
# ------------------------------------------------------------------ #

@_ltype_router.get("", response_model=DataResponse[list[LeaveTypeRead]])
async def list_leave_types(
    is_active: bool | None = None,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(LeaveType)
    if is_active is not None:
        q = q.where(LeaveType.is_active == is_active)
    result = await db.execute(q.order_by(LeaveType.name))
    return DataResponse(data=[LeaveTypeRead.model_validate(lt) for lt in result.scalars().all()])


@_ltype_router.post("", response_model=DataResponse[LeaveTypeRead], status_code=201)
async def create_leave_type(
    payload: LeaveTypeCreate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lt = LeaveType(**payload.model_dump())
    db.add(lt)
    await db.flush()
    await db.refresh(lt)
    return DataResponse(data=LeaveTypeRead.model_validate(lt))


@_ltype_router.patch("/{leave_type_id}", response_model=DataResponse[LeaveTypeRead])
async def update_leave_type(
    leave_type_id: UUID,
    payload: LeaveTypeUpdate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(LeaveType).where(LeaveType.id == leave_type_id))
    lt = result.scalar_one_or_none()
    if lt is None:
        raise HTTPException(status_code=404, detail="Leave type not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(lt, key, value)
    await db.flush()
    await db.refresh(lt)
    return DataResponse(data=LeaveTypeRead.model_validate(lt))


# ------------------------------------------------------------------ #
# Leave Requests                                                      #
# ------------------------------------------------------------------ #

@_lreq_router.get("", response_model=PaginatedResponse[LeaveRequestRead])
async def list_leave_requests(
    page: int = 1,
    page_size: int = 50,
    user_id: UUID | None = None,
    status: LeaveStatusEnum | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(LeaveRequest)
    # Non-managers can only see their own requests
    filter_user_id = user_id or current_user.id
    q = q.where(LeaveRequest.user_id == filter_user_id)
    if status:
        q = q.where(LeaveRequest.status == status)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    result = await db.execute(q.order_by(LeaveRequest.start_date.desc()).offset((page - 1) * page_size).limit(page_size))
    return PaginatedResponse(
        data=[LeaveRequestRead.model_validate(r) for r in result.scalars().all()],
        total=total,
        page=page,
        page_size=page_size,
    )


@_lreq_router.post("", response_model=DataResponse[LeaveRequestRead], status_code=201)
async def create_leave_request(
    payload: LeaveRequestCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    req = LeaveRequest(**payload.model_dump(), user_id=user.id)
    # Increment pending balance if balance record exists
    bal_result = await db.execute(
        select(LeaveBalance).where(
            LeaveBalance.user_id == user.id,
            LeaveBalance.leave_type_id == payload.leave_type_id,
            LeaveBalance.year == payload.start_date.year,
        )
    )
    bal = bal_result.scalar_one_or_none()
    if bal:
        bal.pending_days = float(bal.pending_days) + float(payload.days_requested)

    db.add(req)
    await db.flush()
    await db.refresh(req)
    return DataResponse(data=LeaveRequestRead.model_validate(req))


@_lreq_router.patch("/{request_id}", response_model=DataResponse[LeaveRequestRead])
async def update_leave_request(
    request_id: UUID,
    payload: LeaveRequestUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(LeaveRequest).where(LeaveRequest.id == request_id))
    req = result.scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=404, detail="Leave request not found")

    updates = payload.model_dump(exclude_unset=True)

    if "status" in updates:
        new_status = updates["status"]
        if new_status in (LeaveStatusEnum.approved, LeaveStatusEnum.rejected):
            req.approved_by = user.id
            req.approved_at = datetime.now(timezone.utc)
            # Adjust balance
            bal_result = await db.execute(
                select(LeaveBalance).where(
                    LeaveBalance.user_id == req.user_id,
                    LeaveBalance.leave_type_id == req.leave_type_id,
                    LeaveBalance.year == req.start_date.year,
                )
            )
            bal = bal_result.scalar_one_or_none()
            if bal:
                bal.pending_days = max(0, float(bal.pending_days) - float(req.days_requested))
                if new_status == LeaveStatusEnum.approved:
                    bal.used_days = float(bal.used_days) + float(req.days_requested)

    for key, value in updates.items():
        setattr(req, key, value)
    await db.flush()
    await db.refresh(req)
    return DataResponse(data=LeaveRequestRead.model_validate(req))


# ------------------------------------------------------------------ #
# Leave Balances                                                      #
# ------------------------------------------------------------------ #

@_lbal_router.get("", response_model=DataResponse[list[LeaveBalanceRead]])
async def list_leave_balances(
    user_id: UUID | None = None,
    year: int | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(LeaveBalance)
    q = q.where(LeaveBalance.user_id == (user_id or current_user.id))
    if year:
        q = q.where(LeaveBalance.year == year)
    result = await db.execute(q)
    balances = result.scalars().all()
    return DataResponse(
        data=[
            LeaveBalanceRead(
                **{c: getattr(b, c) for c in ["id", "user_id", "leave_type_id", "year",
                                               "entitled_days", "used_days", "pending_days",
                                               "carried_over_days", "created_at", "updated_at"]},
                remaining_days=b.remaining_days,
            )
            for b in balances
        ]
    )


@_lbal_router.put("", response_model=DataResponse[LeaveBalanceRead], status_code=200)
async def upsert_leave_balance(
    payload: LeaveBalanceUpsert,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(LeaveBalance).where(
            LeaveBalance.user_id == payload.user_id,
            LeaveBalance.leave_type_id == payload.leave_type_id,
            LeaveBalance.year == payload.year,
        )
    )
    bal = result.scalar_one_or_none()
    if bal is None:
        bal = LeaveBalance(
            user_id=payload.user_id,
            leave_type_id=payload.leave_type_id,
            year=payload.year,
            entitled_days=payload.entitled_days,
            carried_over_days=payload.carried_over_days,
        )
        db.add(bal)
    else:
        bal.entitled_days = payload.entitled_days
        bal.carried_over_days = payload.carried_over_days
    await db.flush()
    await db.refresh(bal)
    return DataResponse(
        data=LeaveBalanceRead(
            **{c: getattr(bal, c) for c in ["id", "user_id", "leave_type_id", "year",
                                             "entitled_days", "used_days", "pending_days",
                                             "carried_over_days", "created_at", "updated_at"]},
            remaining_days=bal.remaining_days,
        )
    )


# Mount sub-routers
router.include_router(_dept_router)
router.include_router(_pos_router)
router.include_router(_ltype_router)
router.include_router(_lreq_router)
router.include_router(_lbal_router)
