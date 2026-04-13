from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.customer import (
    Customer,
    CustomerAddress,
    LoyaltyAccount,
    LoyaltyTransaction,
    LoyaltyTierEnum,
)
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.customer import (
    CustomerAddressCreate,
    CustomerAddressRead,
    CustomerAddressUpdate,
    CustomerCreate,
    CustomerRead,
    CustomerUpdate,
    LoyaltyAccountCreate,
    LoyaltyAccountRead,
    LoyaltyTransactionCreate,
    LoyaltyTransactionRead,
)

router = APIRouter(prefix="/api/customers", tags=["customers"])


def _loyalty_tier_from_lifetime(lifetime_pts: int) -> LoyaltyTierEnum:
    if lifetime_pts >= 10000:
        return LoyaltyTierEnum.platinum
    if lifetime_pts >= 5000:
        return LoyaltyTierEnum.gold
    if lifetime_pts >= 1000:
        return LoyaltyTierEnum.silver
    return LoyaltyTierEnum.bronze


# ------------------------------------------------------------------ #
# Customers                                                           #
# ------------------------------------------------------------------ #

@router.get("", response_model=PaginatedResponse[CustomerRead])
async def list_customers(
    page: int = 1,
    page_size: int = 50,
    search: str | None = Query(None, max_length=100),
    is_active: bool | None = None,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Customer)
    if search:
        term = f"%{search}%"
        q = q.where(
            Customer.first_name.ilike(term)
            | Customer.last_name.ilike(term)
            | Customer.email.ilike(term)
            | Customer.phone.ilike(term)
            | Customer.customer_code.ilike(term)
        )
    if is_active is not None:
        q = q.where(Customer.is_active == is_active)

    count_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = count_result.scalar() or 0

    result = await db.execute(q.offset((page - 1) * page_size).limit(page_size))
    customers = result.scalars().all()

    return PaginatedResponse(
        data=[CustomerRead.model_validate(c) for c in customers],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{customer_id}", response_model=DataResponse[CustomerRead])
async def get_customer(
    customer_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return DataResponse(data=CustomerRead.model_validate(customer))


@router.post("", response_model=DataResponse[CustomerRead], status_code=201)
async def create_customer(
    payload: CustomerCreate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    customer = Customer(**payload.model_dump())
    db.add(customer)
    await db.flush()
    await db.refresh(customer)
    return DataResponse(data=CustomerRead.model_validate(customer))


@router.patch("/{customer_id}", response_model=DataResponse[CustomerRead])
async def update_customer(
    customer_id: UUID,
    payload: CustomerUpdate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(customer, key, value)
    await db.flush()
    await db.refresh(customer)
    return DataResponse(data=CustomerRead.model_validate(customer))


@router.delete("/{customer_id}", status_code=204)
async def delete_customer(
    customer_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    await db.delete(customer)


# ------------------------------------------------------------------ #
# Customer Addresses                                                  #
# ------------------------------------------------------------------ #

@router.get("/{customer_id}/addresses", response_model=DataResponse[list[CustomerAddressRead]])
async def list_addresses(
    customer_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CustomerAddress).where(CustomerAddress.customer_id == customer_id)
    )
    return DataResponse(data=[CustomerAddressRead.model_validate(a) for a in result.scalars().all()])


@router.post("/{customer_id}/addresses", response_model=DataResponse[CustomerAddressRead], status_code=201)
async def add_address(
    customer_id: UUID,
    payload: CustomerAddressCreate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    address = CustomerAddress(**payload.model_dump(), customer_id=customer_id)
    db.add(address)
    await db.flush()
    await db.refresh(address)
    return DataResponse(data=CustomerAddressRead.model_validate(address))


@router.patch("/{customer_id}/addresses/{address_id}", response_model=DataResponse[CustomerAddressRead])
async def update_address(
    customer_id: UUID,
    address_id: UUID,
    payload: CustomerAddressUpdate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CustomerAddress).where(
            CustomerAddress.id == address_id, CustomerAddress.customer_id == customer_id
        )
    )
    address = result.scalar_one_or_none()
    if address is None:
        raise HTTPException(status_code=404, detail="Address not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(address, key, value)
    await db.flush()
    await db.refresh(address)
    return DataResponse(data=CustomerAddressRead.model_validate(address))


@router.delete("/{customer_id}/addresses/{address_id}", status_code=204)
async def delete_address(
    customer_id: UUID,
    address_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CustomerAddress).where(
            CustomerAddress.id == address_id, CustomerAddress.customer_id == customer_id
        )
    )
    address = result.scalar_one_or_none()
    if address is None:
        raise HTTPException(status_code=404, detail="Address not found")
    await db.delete(address)


# ------------------------------------------------------------------ #
# Loyalty                                                             #
# ------------------------------------------------------------------ #

@router.get("/{customer_id}/loyalty", response_model=DataResponse[LoyaltyAccountRead])
async def get_loyalty_account(
    customer_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(LoyaltyAccount).where(LoyaltyAccount.customer_id == customer_id)
    )
    acct = result.scalar_one_or_none()
    if acct is None:
        raise HTTPException(status_code=404, detail="No loyalty account found")
    return DataResponse(data=LoyaltyAccountRead.model_validate(acct))


@router.post("/{customer_id}/loyalty", response_model=DataResponse[LoyaltyAccountRead], status_code=201)
async def create_loyalty_account(
    customer_id: UUID,
    payload: LoyaltyAccountCreate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(LoyaltyAccount).where(LoyaltyAccount.customer_id == customer_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Loyalty account already exists")
    acct = LoyaltyAccount(customer_id=customer_id, joined_date=payload.joined_date)
    db.add(acct)
    await db.flush()
    await db.refresh(acct)
    return DataResponse(data=LoyaltyAccountRead.model_validate(acct))


@router.post("/{customer_id}/loyalty/transactions", response_model=DataResponse[LoyaltyTransactionRead], status_code=201)
async def add_loyalty_transaction(
    customer_id: UUID,
    payload: LoyaltyTransactionCreate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    acct_result = await db.execute(
        select(LoyaltyAccount).where(LoyaltyAccount.customer_id == customer_id)
    )
    acct = acct_result.scalar_one_or_none()
    if acct is None:
        raise HTTPException(status_code=404, detail="No loyalty account found")

    txn = LoyaltyTransaction(loyalty_account_id=acct.id, **payload.model_dump())
    acct.points_balance += payload.points
    if payload.points > 0:
        acct.lifetime_points += payload.points
    acct.tier = _loyalty_tier_from_lifetime(acct.lifetime_points)

    db.add(txn)
    await db.flush()
    await db.refresh(txn)
    return DataResponse(data=LoyaltyTransactionRead.model_validate(txn))


@router.get("/{customer_id}/loyalty/transactions", response_model=PaginatedResponse[LoyaltyTransactionRead])
async def list_loyalty_transactions(
    customer_id: UUID,
    page: int = 1,
    page_size: int = 50,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    acct_result = await db.execute(
        select(LoyaltyAccount).where(LoyaltyAccount.customer_id == customer_id)
    )
    acct = acct_result.scalar_one_or_none()
    if acct is None:
        raise HTTPException(status_code=404, detail="No loyalty account found")

    q = select(LoyaltyTransaction).where(LoyaltyTransaction.loyalty_account_id == acct.id)
    count = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    result = await db.execute(q.offset((page - 1) * page_size).limit(page_size))
    return PaginatedResponse(
        data=[LoyaltyTransactionRead.model_validate(t) for t in result.scalars().all()],
        total=count,
        page=page,
        page_size=page_size,
    )
