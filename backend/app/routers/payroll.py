from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.payroll import (
    EmployeeProfile,
    NationalityEnum,
    PayrollRun,
    PayrollStatusEnum,
    PaySlip,
)
from app.models.user import RoleEnum, User, UserStoreRole
from app.auth.dependencies import (
    get_current_user,
    require_self_or_store_manager,
    require_store_role,
)
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.payroll import (
    EmployeeProfileCreate,
    EmployeeProfileRead,
    EmployeeProfileUpdate,
    PayrollRunCreate,
    PayrollRunRead,
    PayrollRunSummary,
    PaySlipAdjust,
    PaySlipRead,
)
from app.services.cpf import calculate_cpf

router = APIRouter(tags=["payroll"])


# ---- Employee Profile endpoints ----


@router.post(
    "/api/employees/{user_id}/profile",
    response_model=DataResponse[EmployeeProfileRead],
    status_code=201,
)
async def create_employee_profile(
    user_id: UUID,
    payload: EmployeeProfileCreate,
    _: UUID = Depends(require_self_or_store_manager),
    db: AsyncSession = Depends(get_db),
):
    # Check if profile already exists
    existing = await db.execute(
        select(EmployeeProfile).where(EmployeeProfile.user_id == user_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="Employee profile already exists")

    data = payload.model_dump()
    data["user_id"] = user_id
    profile = EmployeeProfile(**data)
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    return DataResponse(data=EmployeeProfileRead.model_validate(profile))


@router.get(
    "/api/employees/{user_id}/profile",
    response_model=DataResponse[EmployeeProfileRead],
)
async def get_employee_profile(
    user_id: UUID,
    _: UUID = Depends(require_self_or_store_manager),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(EmployeeProfile).where(EmployeeProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Employee profile not found")
    return DataResponse(data=EmployeeProfileRead.model_validate(profile))


@router.patch(
    "/api/employees/{user_id}/profile",
    response_model=DataResponse[EmployeeProfileRead],
)
async def update_employee_profile(
    user_id: UUID,
    payload: EmployeeProfileUpdate,
    _: UUID = Depends(require_self_or_store_manager),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(EmployeeProfile).where(EmployeeProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Employee profile not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)

    await db.flush()
    await db.refresh(profile)
    return DataResponse(data=EmployeeProfileRead.model_validate(profile))


@router.get(
    "/api/stores/{store_id}/payroll/employees",
    response_model=PaginatedResponse[EmployeeProfileRead],
)
async def list_payroll_employees(
    store_id: UUID,
    page: int = 1,
    page_size: int = 50,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    role_result = await db.execute(
        select(UserStoreRole.user_id).where(UserStoreRole.store_id == store_id)
    )
    user_ids = [row[0] for row in role_result.all()]

    if not user_ids:
        return PaginatedResponse(data=[], total=0, page=page, page_size=page_size)

    base = select(EmployeeProfile).where(EmployeeProfile.user_id.in_(user_ids))
    from sqlalchemy import func
    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar() or 0

    result = await db.execute(base.offset((page - 1) * page_size).limit(page_size))
    profiles = result.scalars().all()
    return PaginatedResponse(
        data=[EmployeeProfileRead.model_validate(p) for p in profiles],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---- Payroll Run endpoints ----


@router.post(
    "/api/stores/{store_id}/payroll",
    response_model=DataResponse[PayrollRunSummary],
    status_code=201,
)
async def create_payroll_run(
    store_id: UUID,
    payload: PayrollRunCreate,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = PayrollRun(
        store_id=store_id,
        period_start=payload.period_start,
        period_end=payload.period_end,
        created_by=user.id,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return DataResponse(data=PayrollRunSummary.model_validate(run))


@router.get(
    "/api/stores/{store_id}/payroll",
    response_model=DataResponse[list[PayrollRunSummary]],
)
async def list_payroll_runs(
    store_id: UUID,
    status: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    query = select(PayrollRun).where(PayrollRun.store_id == store_id)
    if status:
        query = query.where(PayrollRun.status == status)
    if period_start:
        query = query.where(PayrollRun.period_start >= period_start)
    if period_end:
        query = query.where(PayrollRun.period_end <= period_end)

    result = await db.execute(query)
    runs = result.scalars().all()
    return DataResponse(
        data=[PayrollRunSummary.model_validate(r) for r in runs]
    )


@router.get(
    "/api/stores/{store_id}/payroll/{run_id}",
    response_model=DataResponse[PayrollRunRead],
)
async def get_payroll_run(
    store_id: UUID,
    run_id: UUID,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PayrollRun).where(
            PayrollRun.id == run_id, PayrollRun.store_id == store_id
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    return DataResponse(data=PayrollRunRead.model_validate(run))


def _calculate_age(dob: date, reference_date: date) -> int:
    """Calculate age in years as of reference_date."""
    age = reference_date.year - dob.year
    if (reference_date.month, reference_date.day) < (dob.month, dob.day):
        age -= 1
    return age


@router.post(
    "/api/stores/{store_id}/payroll/{run_id}/calculate",
    response_model=DataResponse[PayrollRunRead],
)
async def calculate_payroll(
    store_id: UUID,
    run_id: UUID,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Get the payroll run
    result = await db.execute(
        select(PayrollRun).where(
            PayrollRun.id == run_id, PayrollRun.store_id == store_id
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Payroll run not found")

    if run.status != PayrollStatusEnum.draft:
        raise HTTPException(
            status_code=400, detail="Payroll run is not in draft status"
        )

    # Get all active employee profiles for employees in this store
    role_result = await db.execute(
        select(UserStoreRole.user_id).where(UserStoreRole.store_id == store_id)
    )
    store_user_ids = [row[0] for row in role_result.all()]

    if not store_user_ids:
        raise HTTPException(
            status_code=400, detail="No employees found for this store"
        )

    profile_result = await db.execute(
        select(EmployeeProfile).where(
            EmployeeProfile.user_id.in_(store_user_ids),
            EmployeeProfile.is_active == True,
        )
    )
    profiles = profile_result.scalars().all()

    if not profiles:
        raise HTTPException(
            status_code=400, detail="No active employee profiles found"
        )

    # Delete existing payslips for this run (recalculation)
    existing_slips = await db.execute(
        select(PaySlip).where(PaySlip.payroll_run_id == run_id)
    )
    for slip in existing_slips.scalars().all():
        await db.delete(slip)
    await db.flush()

    total_gross = Decimal("0")
    total_cpf_ee = Decimal("0")
    total_cpf_er = Decimal("0")
    total_net = Decimal("0")

    for profile in profiles:
        age = _calculate_age(profile.date_of_birth, run.period_end)
        basic = Decimal(str(profile.basic_salary))
        gross_pay = basic

        # CPF calculation
        cpf_ee = Decimal("0")
        cpf_er = Decimal("0")

        if profile.nationality != NationalityEnum.foreigner:
            cpf_result = calculate_cpf(
                age=age,
                ordinary_wages=gross_pay,
            )
            cpf_ee = cpf_result.employee_contribution
            cpf_er = cpf_result.employer_contribution

        net_pay = gross_pay - cpf_ee

        slip = PaySlip(
            payroll_run_id=run_id,
            user_id=profile.user_id,
            basic_salary=float(basic),
            gross_pay=float(gross_pay),
            cpf_employee=float(cpf_ee),
            cpf_employer=float(cpf_er),
            net_pay=float(net_pay),
        )
        db.add(slip)

        total_gross += gross_pay
        total_cpf_ee += cpf_ee
        total_cpf_er += cpf_er
        total_net += net_pay

    # Update run totals
    run.total_gross = float(total_gross)
    run.total_cpf_employee = float(total_cpf_ee)
    run.total_cpf_employer = float(total_cpf_er)
    run.total_net = float(total_net)
    run.status = PayrollStatusEnum.calculated

    await db.flush()
    await db.refresh(run)
    return DataResponse(data=PayrollRunRead.model_validate(run))


@router.patch(
    "/api/stores/{store_id}/payroll/{run_id}/payslips/{slip_id}",
    response_model=DataResponse[PaySlipRead],
)
async def adjust_payslip(
    store_id: UUID,
    run_id: UUID,
    slip_id: UUID,
    payload: PaySlipAdjust,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    # Verify the run belongs to the store
    run_result = await db.execute(
        select(PayrollRun).where(
            PayrollRun.id == run_id, PayrollRun.store_id == store_id
        )
    )
    run = run_result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Payroll run not found")

    result = await db.execute(
        select(PaySlip).where(
            PaySlip.id == slip_id, PaySlip.payroll_run_id == run_id
        )
    )
    slip = result.scalar_one_or_none()
    if slip is None:
        raise HTTPException(status_code=404, detail="Payslip not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(slip, key, value)

    # Recalculate derived totals
    slip.gross_pay = float(
        Decimal(str(slip.basic_salary))
        + Decimal(str(slip.overtime_pay))
        + Decimal(str(slip.allowances))
        - Decimal(str(slip.deductions))
    )
    slip.net_pay = float(
        Decimal(str(slip.gross_pay)) - Decimal(str(slip.cpf_employee))
    )

    await db.flush()
    await db.refresh(slip)

    # Recalculate parent PayrollRun totals
    all_slips_result = await db.execute(
        select(PaySlip).where(PaySlip.payroll_run_id == run_id)
    )
    all_slips = all_slips_result.scalars().all()
    run.total_gross = float(sum(Decimal(str(s.gross_pay)) for s in all_slips))
    run.total_cpf_employee = float(sum(Decimal(str(s.cpf_employee)) for s in all_slips))
    run.total_cpf_employer = float(sum(Decimal(str(s.cpf_employer)) for s in all_slips))
    run.total_net = float(sum(Decimal(str(s.net_pay)) for s in all_slips))
    await db.flush()

    return DataResponse(data=PaySlipRead.model_validate(slip))


@router.post(
    "/api/stores/{store_id}/payroll/{run_id}/approve",
    response_model=DataResponse[PayrollRunSummary],
)
async def approve_payroll(
    store_id: UUID,
    run_id: UUID,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.owner)),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PayrollRun).where(
            PayrollRun.id == run_id, PayrollRun.store_id == store_id
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Payroll run not found")

    if run.status != PayrollStatusEnum.calculated:
        raise HTTPException(
            status_code=400,
            detail="Payroll run must be in calculated status to approve",
        )

    if run.created_by == user.id:
        raise HTTPException(
            status_code=400,
            detail="Payroll run cannot be approved by its creator (separation of duties)",
        )

    run.status = PayrollStatusEnum.approved
    run.approved_by = user.id

    await db.flush()
    await db.refresh(run)
    return DataResponse(data=PayrollRunSummary.model_validate(run))
