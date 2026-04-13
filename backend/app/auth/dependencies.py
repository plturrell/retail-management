from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.user import RoleEnum, User, UserStoreRole
from app.auth.firebase import verify_firebase_token

# Role hierarchy: owner > manager > staff
ROLE_HIERARCHY = {
    RoleEnum.staff: 0,
    RoleEnum.manager: 1,
    RoleEnum.owner: 2,
}


def _extract_bearer_token(request: Request) -> str:
    """Extract Bearer token from the Authorization header."""
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return parts[1]


async def get_token_claims(request: Request) -> dict[str, Any]:
    """Verify the bearer token and return decoded Firebase claims."""
    token = _extract_bearer_token(request)
    decoded = await verify_firebase_token(token)
    firebase_uid = decoded.get("uid")
    if not firebase_uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing uid claim",
        )
    return decoded


async def get_current_user(
    claims: dict[str, Any] = Depends(get_token_claims),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency that verifies the Firebase JWT and returns the DB User."""
    firebase_uid = claims["uid"]

    result = await db.execute(
        select(User)
        .options(selectinload(User.store_roles))
        .where(User.firebase_uid == firebase_uid)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found in database",
        )
    return user


def get_store_role(user: User, store_id: UUID) -> UserStoreRole | None:
    """Return the user's role assignment for the store, if any."""
    for assignment in user.store_roles:
        if assignment.store_id == store_id:
            return assignment
    return None


def ensure_store_access(user: User, store_id: UUID) -> UserStoreRole:
    """Ensure the user belongs to the requested store."""
    assignment = get_store_role(user, store_id)
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this store",
        )
    return assignment


def ensure_store_role(
    user: User,
    store_id: UUID,
    min_role: RoleEnum,
) -> UserStoreRole:
    """Ensure the user has at least the required role for the store."""
    assignment = ensure_store_access(user, store_id)
    user_level = ROLE_HIERARCHY.get(assignment.role, -1)
    required_level = ROLE_HIERARCHY.get(min_role, 0)
    if user_level < required_level:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires at least {min_role.value} role",
        )
    return assignment


async def require_store_access(
    store_id: UUID,
    user: User = Depends(get_current_user),
) -> UserStoreRole:
    """FastAPI dependency for store membership checks on store-scoped routes."""
    return ensure_store_access(user, store_id)


def require_store_role(min_role: RoleEnum):
    """FastAPI dependency factory for store role checks on store-scoped routes."""

    async def dependency(
        store_id: UUID,
        user: User = Depends(get_current_user),
    ) -> UserStoreRole:
        return ensure_store_role(user, store_id, min_role)

    return dependency


async def require_self_or_store_manager(
    user_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UUID:
    """Allow users to manage their own profile, or managers of a shared store."""
    if user.id == user_id:
        return user_id

    result = await db.execute(
        select(UserStoreRole.store_id).where(UserStoreRole.user_id == user_id)
    )
    target_store_ids = {row[0] for row in result.all()}
    if not target_store_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage this employee",
        )

    requester_roles = {
        assignment.store_id: assignment.role for assignment in user.store_roles
    }
    for store_id in target_store_ids:
        requester_role = requester_roles.get(store_id)
        if requester_role is None:
            continue
        if ROLE_HIERARCHY.get(requester_role, -1) >= ROLE_HIERARCHY[RoleEnum.manager]:
            return user_id

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to manage this employee",
    )


