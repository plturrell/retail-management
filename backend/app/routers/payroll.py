from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.payroll import (
    CommissionEntry,
    CommissionRule,
    EmployeeProfile,
    NationalityEnum,
    PayrollRun,
    PayrollStatusEnum,
    PaySlip,
)
from app.models.order import Order, OrderStatus
from app.models.timesheet import TimeEntry, TimeEntryStatus
from app.models.user import RoleEnum, User, UserStoreRole
from app.auth.dependencies import (
    get_current_user,
    require_self_or_store_manager,
    require_store_role,
)
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.payroll import (
    CommissionRuleCreate,
    CommissionRuleRead,
    CommissionRuleUpdate,
    EmployeeProfileCreate,
    EmployeeProfileRead,
    EmployeeProfileUpdate,
    PayrollRunCreate,
    PayrollRunRead,
    PayrollRunSummary,
    PaySlipAdjust,
    PaySlipRead,
)
from app.services.commission import (
    calculate_commission,
    calculate_flat_commission,
    parse_tiers,
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


# Singapore standard overtime threshold: 44 hours per week
_SG_WEEKLY_OT_THRESHOLD = Decimal("44")
_SG_OT_MULTIPLIER = Decimal("1.5")


def _compute_timesheet_hours(
    entries: list[TimeEntry],
    period_start: date,
    period_end: date,
) -> tuple[Decimal, Decimal]:
    """Compute total regular hours and overtime hours from approved time entries.

    Overtime is calculated per ISO week: hours exceeding 44 in a single week
    are classified as overtime (Singapore Employment Act standard).

    Returns (regular_hours, overtime_hours).
    """
    # Bucket hours by ISO week number
    weekly_hours: dict[tuple[int, int], Decimal] = defaultdict(Decimal)

    for entry in entries:
        if entry.clock_out is None:
            continue
        delta = entry.clock_out - entry.clock_in
        worked_seconds = max(delta.total_seconds() - entry.break_minutes * 60, 0)
        worked_hours = Decimal(str(round(worked_seconds / 3600, 2)))
        iso_year, iso_week, _ = entry.clock_in.isocalendar()
        weekly_hours[(iso_year, iso_week)] += worked_hours

    total_regular = Decimal("0")
    total_overtime = Decimal("0")

    for _week_key, hours in weekly_hours.items():
        if hours > _SG_WEEKLY_OT_THRESHOLD:
            total_regular += _SG_WEEKLY_OT_THRESHOLD
            total_overtime += hours - _SG_WEEKLY_OT_THRESHOLD
        else:
            total_regular += hours

    return total_regular, total_overtime


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

    # Delete existing commission entries for payslips in this run
    existing_entries = await db.execute(
        select(CommissionEntry).where(
            CommissionEntry.payslip_id.in_(
                select(PaySlip.id).where(PaySlip.payroll_run_id == run_id)
            )
        )
    )
    for entry in existing_entries.scalars().all():
        await db.delete(entry)
    await db.flush()

    # Fetch active commission rules for this store
    comm_rule_result = await db.execute(
        select(CommissionRule).where(
            CommissionRule.store_id == store_id,
            CommissionRule.is_active == True,
        )
    )
    commission_rules = comm_rule_result.scalars().all()

    # Fetch completed orders for the period, grouped by salesperson
    order_result = await db.execute(
        select(Order).where(
            Order.store_id == store_id,
            Order.status == OrderStatus.completed,
            Order.order_date >= datetime.combine(run.period_start, datetime.min.time()),
            Order.order_date <= datetime.combine(run.period_end, datetime.max.time()),
        )
    )
    all_orders = order_result.scalars().all()

    # Sum sales by salesperson_id (fallback to staff_id)
    user_sales: dict[UUID, Decimal] = defaultdict(lambda: Decimal("0"))
    for order in all_orders:
        seller_id = order.salesperson_id or order.staff_id
        if seller_id:
            user_sales[seller_id] += Decimal(str(order.grand_total))

    # Fetch approved timesheet entries for the pay period for all store employees
    period_start_dt = datetime.combine(run.period_start, datetime.min.time())
    period_end_dt = datetime.combine(run.period_end, datetime.max.time())

    ts_result = await db.execute(
        select(TimeEntry).where(
            TimeEntry.store_id == store_id,
            TimeEntry.user_id.in_(store_user_ids),
            TimeEntry.status == TimeEntryStatus.approved,
            TimeEntry.clock_in >= period_start_dt,
            TimeEntry.clock_in <= period_end_dt,
            TimeEntry.clock_out.isnot(None),
        )
    )
    all_time_entries = ts_result.scalars().all()

    # Group time entries by user
    user_time_entries: dict[UUID, list[TimeEntry]] = defaultdict(list)
    for te in all_time_entries:
        user_time_entries[te.user_id].append(te)

    total_gross = Decimal("0")
    total_cpf_ee = Decimal("0")
    total_cpf_er = Decimal("0")
    total_net = Decimal("0")

    for profile in profiles:
        age = _calculate_age(profile.date_of_birth, run.period_end)
        basic = Decimal(str(profile.basic_salary))

        entries = user_time_entries.get(profile.user_id, [])
        regular_hours, overtime_hours = _compute_timesheet_hours(
            entries, run.period_start, run.period_end
        )
        total_hours = regular_hours + overtime_hours

        if profile.hourly_rate is not None:
            # Hourly-rate staff: gross = hours × hourly_rate + overtime_pay
            rate = Decimal(str(profile.hourly_rate))
            overtime_pay = overtime_hours * rate * _SG_OT_MULTIPLIER
            gross_pay = regular_hours * rate + overtime_pay
        else:
            # Salaried staff: use basic_salary, populate hours for records
            overtime_pay = Decimal("0")
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

        # Commission calculation
        emp_sales = user_sales.get(profile.user_id, Decimal("0"))
        commission_amount = Decimal("0")

        if emp_sales > 0:
            if commission_rules:
                # Use store commission rules (tiered)
                for rule in commission_rules:
                    tiers = parse_tiers(rule.tiers)
                    commission_amount += calculate_commission(emp_sales, tiers)
            elif profile.commission_rate is not None and profile.commission_rate > 0:
                # Fallback to employee flat rate
                rate = Decimal(str(profile.commission_rate)) / Decimal("100")
                commission_amount = calculate_flat_commission(emp_sales, rate)

        gross_pay += commission_amount
        net_pay = gross_pay - cpf_ee

        slip = PaySlip(
            payroll_run_id=run_id,
            user_id=profile.user_id,
            basic_salary=float(basic),
            hours_worked=float(total_hours),
            overtime_hours=float(overtime_hours),
            overtime_pay=float(overtime_pay),
            commission_sales=float(emp_sales),
            commission_amount=float(commission_amount),
            gross_pay=float(gross_pay),
            cpf_employee=float(cpf_ee),
            cpf_employer=float(cpf_er),
            net_pay=float(net_pay),
        )
        db.add(slip)
        await db.flush()
        await db.refresh(slip)

        # Create commission entries for audit trail
        if commission_amount > 0 and commission_rules:
            for rule in commission_rules:
                tiers = parse_tiers(rule.tiers)
                rule_commission = calculate_commission(emp_sales, tiers)
                if rule_commission > 0:
                    entry = CommissionEntry(
                        payslip_id=slip.id,
                        commission_rule_id=rule.id,
                        sales_amount=float(emp_sales),
                        commission_amount=float(rule_commission),
                        rule_name=rule.name,
                    )
                    db.add(entry)

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
        + Decimal(str(slip.commission_amount))
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



# ---- Commission Rule endpoints ----


@router.post(
    "/api/stores/{store_id}/commission-rules",
    response_model=DataResponse[CommissionRuleRead],
    status_code=201,
)
async def create_commission_rule(
    store_id: UUID,
    payload: CommissionRuleCreate,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    import json

    rule = CommissionRule(
        store_id=store_id,
        name=payload.name,
        tiers=json.dumps([t.model_dump(mode="json") for t in payload.tiers]),
        is_active=payload.is_active,
    )
    db.add(rule)
    await db.flush()
    await db.refresh(rule)
    return DataResponse(data=CommissionRuleRead.model_validate(rule))


@router.get(
    "/api/stores/{store_id}/commission-rules",
    response_model=DataResponse[list[CommissionRuleRead]],
)
async def list_commission_rules(
    store_id: UUID,
    active_only: bool = True,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    query = select(CommissionRule).where(CommissionRule.store_id == store_id)
    if active_only:
        query = query.where(CommissionRule.is_active == True)

    result = await db.execute(query)
    rules = result.scalars().all()
    return DataResponse(
        data=[CommissionRuleRead.model_validate(r) for r in rules]
    )


@router.get(
    "/api/stores/{store_id}/commission-rules/{rule_id}",
    response_model=DataResponse[CommissionRuleRead],
)
async def get_commission_rule(
    store_id: UUID,
    rule_id: UUID,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CommissionRule).where(
            CommissionRule.id == rule_id,
            CommissionRule.store_id == store_id,
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Commission rule not found")
    return DataResponse(data=CommissionRuleRead.model_validate(rule))


@router.patch(
    "/api/stores/{store_id}/commission-rules/{rule_id}",
    response_model=DataResponse[CommissionRuleRead],
)
async def update_commission_rule(
    store_id: UUID,
    rule_id: UUID,
    payload: CommissionRuleUpdate,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    import json

    result = await db.execute(
        select(CommissionRule).where(
            CommissionRule.id == rule_id,
            CommissionRule.store_id == store_id,
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Commission rule not found")

    updates = payload.model_dump(exclude_unset=True)
    if "tiers" in updates and updates["tiers"] is not None:
        updates["tiers"] = json.dumps(
            [t.model_dump(mode="json") for t in payload.tiers]
        )
    for key, value in updates.items():
        setattr(rule, key, value)

    await db.flush()
    await db.refresh(rule)
    return DataResponse(data=CommissionRuleRead.model_validate(rule))


@router.delete(
    "/api/stores/{store_id}/commission-rules/{rule_id}",
    response_model=DataResponse[dict],
)
async def delete_commission_rule(
    store_id: UUID,
    rule_id: UUID,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CommissionRule).where(
            CommissionRule.id == rule_id,
            CommissionRule.store_id == store_id,
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Commission rule not found")

    await db.delete(rule)
    await db.flush()
    return DataResponse(data={"deleted": True})