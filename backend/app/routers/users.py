from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.user import RoleEnum, User, UserStoreRole
from app.auth.dependencies import get_current_user
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.user import (
    StoreEmployeeRead,
    UserCreate,
    UserMeRead,
    UserRead,
    UserStoreRoleCreate,
    UserStoreRoleRead,
    UserUpdate,
)

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=DataResponse[UserMeRead])
async def get_current_user_profile(
    user: User = Depends(get_current_user),
):
    return DataResponse(data=UserMeRead.model_validate(user))


@router.post("", response_model=DataResponse[UserRead], status_code=201)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(User).where(User.firebase_uid == payload.firebase_uid)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User already exists")

    user = User(**payload.model_dump())
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return DataResponse(data=UserRead.model_validate(user))


@router.patch("/me", response_model=DataResponse[UserRead])
async def update_current_user(
    payload: UserUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, key, value)
    await db.flush()
    await db.refresh(user)
    return DataResponse(data=UserRead.model_validate(user))


@router.post("/roles", response_model=DataResponse[UserStoreRoleRead], status_code=201)
async def assign_store_role(
    payload: UserStoreRoleCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    role = UserStoreRole(**payload.model_dump())
    db.add(role)
    await db.flush()
    await db.refresh(role)
    return DataResponse(data=UserStoreRoleRead.model_validate(role))



@router.get(
    "/stores/{store_id}/employees",
    response_model=PaginatedResponse[StoreEmployeeRead],
)
async def list_store_employees(
    store_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserStoreRole)
        .options(selectinload(UserStoreRole.user))
        .where(UserStoreRole.store_id == store_id)
    )
    roles = result.scalars().all()
    employees = [
        StoreEmployeeRead(
            id=r.user.id,
            full_name=r.user.full_name,
            email=r.user.email,
            phone=r.user.phone,
            role=r.role.value,
        )
        for r in roles
        if r.user is not None
    ]
    return PaginatedResponse(
        data=employees,
        total=len(employees),
        page=1,
        page_size=len(employees),
    )
