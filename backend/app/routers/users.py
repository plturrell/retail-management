import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.user import RoleEnum, User, UserStoreRole
from app.auth.dependencies import (
    ensure_store_role,
    get_current_user,
    get_token_claims,
    require_store_role,
)
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.user import (
    StoreEmployeeRead,
    UserCreate,
    UserMeRead,
    UserRead,
    UserStoreRoleCreate,
    UserStoreRoleRead,
    UserStoreRoleUpdate,
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
    claims: dict = Depends(get_token_claims),
    db: AsyncSession = Depends(get_db),
):
    if claims.get("uid") != payload.firebase_uid:
        raise HTTPException(
            status_code=403,
            detail="Authenticated users may only create their own user record",
        )

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
    result = await db.execute(select(User).where(User.id == user.id))
    db_user = result.scalar_one()
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(db_user, key, value)
    await db.flush()
    await db.refresh(db_user)
    return DataResponse(data=UserRead.model_validate(db_user))


@router.post("/roles", response_model=DataResponse[UserStoreRoleRead], status_code=201)
async def assign_store_role(
    payload: UserStoreRoleCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ensure_store_role(user, payload.store_id, RoleEnum.owner)

    target_user = await db.execute(select(User).where(User.id == payload.user_id))
    if target_user.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="User not found")

    existing_role = await db.execute(
        select(UserStoreRole).where(
            UserStoreRole.user_id == payload.user_id,
            UserStoreRole.store_id == payload.store_id,
        )
    )
    if existing_role.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="User already has a role for this store")

    role = UserStoreRole(**payload.model_dump())
    db.add(role)
    await db.flush()
    await db.refresh(role)
    return DataResponse(data=UserStoreRoleRead.model_validate(role))



@router.patch("/roles/{role_id}", response_model=DataResponse[UserStoreRoleRead])
async def update_store_role(
    role_id: UUID,
    payload: UserStoreRoleUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserStoreRole).where(UserStoreRole.id == role_id)
    )
    role_assignment = result.scalar_one_or_none()
    if role_assignment is None:
        raise HTTPException(status_code=404, detail="Role assignment not found")

    ensure_store_role(user, role_assignment.store_id, RoleEnum.owner)

    try:
        new_role = RoleEnum(payload.role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid role: {payload.role}")

    role_assignment.role = new_role
    await db.flush()
    await db.refresh(role_assignment)
    return DataResponse(data=UserStoreRoleRead.model_validate(role_assignment))


@router.delete("/roles/{role_id}", status_code=204)
async def remove_store_role(
    role_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserStoreRole).where(UserStoreRole.id == role_id)
    )
    role_assignment = result.scalar_one_or_none()
    if role_assignment is None:
        raise HTTPException(status_code=404, detail="Role assignment not found")

    ensure_store_role(user, role_assignment.store_id, RoleEnum.owner)

    if role_assignment.user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot remove your own role")

    await db.delete(role_assignment)


@router.get("/search", response_model=DataResponse[list[UserRead]])
async def search_users(
    email: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    escaped = re.sub(r"([%_\\])", r"\\\1", email)
    result = await db.execute(
        select(User).where(User.email.ilike(f"%{escaped}%")).limit(10)
    )
    users = result.scalars().all()
    return DataResponse(data=[UserRead.model_validate(u) for u in users])


@router.get(
    "/stores/{store_id}/employees",
    response_model=PaginatedResponse[StoreEmployeeRead],
)
async def list_store_employees(
    store_id: UUID,
    _: UserStoreRole = Depends(require_store_role(RoleEnum.manager)),
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
            role_id=r.id,
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
