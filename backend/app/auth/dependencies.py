from __future__ import annotations

from functools import wraps
from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency that verifies the Firebase JWT and returns the DB User."""
    token = _extract_bearer_token(request)
    decoded = await verify_firebase_token(token)
    firebase_uid = decoded.get("uid")
    if not firebase_uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing uid claim",
        )

    result = await db.execute(
        select(User).where(User.firebase_uid == firebase_uid)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found in database",
        )
    return user


def require_role(min_role: RoleEnum, store_id_param: str = "store_id"):
    """Decorator factory that enforces a minimum role for a store.

    Usage:
        @router.get("/stores/{store_id}/inventory")
        @require_role(RoleEnum.manager)
        async def list_inventory(store_id: UUID, user: User = Depends(get_current_user), ...):
            ...

    The decorated function must accept `store_id` (or whatever name is
    passed via `store_id_param`) as a keyword argument, plus the `user`
    dependency.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user: User | None = kwargs.get("user")
            store_id = kwargs.get(store_id_param)

            if user is None or store_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Missing user or store_id for role check",
                )

            # Find the user's role for this store
            role_assignment = None
            for ur in user.store_roles:
                if str(ur.store_id) == str(store_id):
                    role_assignment = ur
                    break

            if role_assignment is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have access to this store",
                )

            user_level = ROLE_HIERARCHY.get(role_assignment.role, -1)
            required_level = ROLE_HIERARCHY.get(min_role, 0)

            if user_level < required_level:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Requires at least {min_role.value} role",
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator
