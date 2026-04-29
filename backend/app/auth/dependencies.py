from __future__ import annotations

from enum import Enum
from typing import Any, List
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
from google.auth.transport import requests as g_requests
from google.cloud.firestore_v1.client import Client as FirestoreClient
from google.oauth2 import id_token

from app.config import settings
from app.firestore import get_firestore_db
from app.firestore_helpers import query_collection
from app.auth.firebase import verify_firebase_token


# ---------------------------------------------------------------------------
# Role enum (replaces the SQLAlchemy model enum)
# ---------------------------------------------------------------------------

class RoleEnum(str, Enum):
    staff = "staff"
    manager = "manager"
    owner = "owner"


# Role hierarchy: owner > manager > staff
ROLE_HIERARCHY = {
    RoleEnum.staff: 0,
    RoleEnum.manager: 1,
    RoleEnum.owner: 2,
}


def _coerce_role(value: RoleEnum | str | None) -> RoleEnum | None:
    if value is None:
        return None
    if isinstance(value, RoleEnum):
        return value
    if isinstance(value, str):
        return RoleEnum(value)
    return None


def _field(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def can_view_sensitive_operations(role: RoleEnum | str | None) -> bool:
    return _coerce_role(role) == RoleEnum.owner


# ---------------------------------------------------------------------------
# Helper data classes (plain dicts with known keys, replacing ORM models)
# ---------------------------------------------------------------------------

class _UserDict(dict):
    """Thin wrapper so user['x'] and user.x both work in downstream code."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


class _RoleDict(dict):
    """Thin wrapper for role-assignment dicts."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Current-user dependency (Firestore-backed)
# ---------------------------------------------------------------------------

async def get_current_user(
    claims: dict[str, Any] = Depends(get_token_claims),
    db: FirestoreClient = Depends(get_firestore_db),
) -> _UserDict:
    """Verify Firebase JWT and return the Firestore user document."""
    firebase_uid: str = claims["uid"]

    user_rows = query_collection(
        "users",
        filters=[("firebase_uid", "==", firebase_uid)],
        limit=1,
    )
    if not user_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found in database",
        )
    user_data = user_rows[0]

    user_id = user_data.get("id")
    user_id_str = str(user_id) if user_id is not None else firebase_uid

    store_roles: List[_RoleDict] = []
    role_docs = db.collection_group("roles").where("user_id", "==", user_id_str).stream()
    for rdoc in role_docs:
        rd = rdoc.to_dict() or {}
        if not rd.get("id"):
            rd["id"] = rdoc.id
        # Extract store_id from the parent path: stores/{storeId}/roles/{userId}
        store_ref = rdoc.reference.parent.parent
        if store_ref:
            rd["store_id"] = UUID(store_ref.id) if _is_uuid(store_ref.id) else store_ref.id
        role_user_id = rd.get("user_id", user_id_str)
        rd["user_id"] = UUID(role_user_id) if _is_uuid(role_user_id) else role_user_id
        if "role" in rd and isinstance(rd["role"], str):
            rd["role"] = RoleEnum(rd["role"])
        store_roles.append(_RoleDict(rd))

    user_data["store_roles"] = store_roles

    if user_id is not None and _is_uuid(str(user_id)):
        user_data["id"] = UUID(str(user_id))

    return _UserDict(user_data)


def _is_uuid(val: str) -> bool:
    try:
        UUID(val)
        return True
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Store-role helpers
# ---------------------------------------------------------------------------

def get_store_role(user: _UserDict, store_id: UUID) -> _RoleDict | None:
    """Return the user's role assignment for the store, if any."""
    for assignment in _field(user, "store_roles", []):
        if _field(assignment, "store_id") == store_id:
            return assignment
    return None


def ensure_store_access(user: _UserDict, store_id: UUID) -> _RoleDict:
    """Ensure the user belongs to the requested store."""
    assignment = get_store_role(user, store_id)
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this store",
        )
    return assignment


def ensure_store_role(
    user: _UserDict,
    store_id: UUID,
    min_role: RoleEnum,
) -> _RoleDict:
    """Ensure the user has at least the required role for the store."""
    assignment = ensure_store_access(user, store_id)
    role_val = _coerce_role(_field(assignment, "role"))
    user_level = ROLE_HIERARCHY.get(role_val, -1)
    required_level = ROLE_HIERARCHY.get(min_role, 0)
    if user_level < required_level:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires at least {min_role.value} role",
        )
    return assignment


def ensure_any_store_role(
    user: _UserDict,
    min_role: RoleEnum,
) -> _RoleDict:
    """Ensure the user has the required role in at least one store."""
    best_assignment: _RoleDict | None = None
    best_level = -1
    required_level = ROLE_HIERARCHY.get(min_role, 0)
    for assignment in _field(user, "store_roles", []):
        role_val = _coerce_role(_field(assignment, "role"))
        level = ROLE_HIERARCHY.get(role_val, -1)
        if level < required_level or level <= best_level:
            continue
        best_assignment = assignment
        best_level = level

    if best_assignment is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires at least {min_role.value} role",
        )
    return best_assignment


async def require_store_access(
    store_id: UUID,
    user: _UserDict = Depends(get_current_user),
) -> _RoleDict:
    """FastAPI dependency for store membership checks on store-scoped routes."""
    return ensure_store_access(user, store_id)


def require_store_role(min_role: RoleEnum):
    """FastAPI dependency factory for store role checks on store-scoped routes."""

    async def dependency(
        store_id: UUID,
        user: _UserDict = Depends(get_current_user),
    ) -> _RoleDict:
        return ensure_store_role(user, store_id, min_role)

    return dependency


def require_any_store_role(min_role: RoleEnum):
    """FastAPI dependency factory for non-store-scoped routes."""

    async def dependency(
        user: _UserDict = Depends(get_current_user),
    ) -> _RoleDict:
        return ensure_any_store_role(user, min_role)

    return dependency


# ---------------------------------------------------------------------------
# Cloud Scheduler OIDC dependency
# ---------------------------------------------------------------------------

# Cached cert fetcher for Google's OIDC verification keys. ``id_token`` reuses
# the JWKS for the process lifetime, so cold-call cost is amortised after the
# first request.
_GOOGLE_REQ = g_requests.Request()


def require_scheduler_oidc(authorization: str | None = Header(default=None)) -> dict:
    """Validate a Google-issued OIDC token from Cloud Scheduler.

    Used to gate ``POST /api/cag/export/push/scheduled`` so only the
    scheduler's service account can trigger the unattended push. Audience must
    match ``settings.CAG_SCHEDULER_AUDIENCE``; email must match
    ``settings.CAG_SCHEDULER_SA_EMAIL`` and be verified.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = id_token.verify_oauth2_token(
            token, _GOOGLE_REQ, audience=settings.CAG_SCHEDULER_AUDIENCE
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid oidc: {exc}",
        ) from exc
    if not claims.get("email_verified"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="email not verified",
        )
    if claims.get("email") != settings.CAG_SCHEDULER_SA_EMAIL:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="wrong service account",
        )
    return {"email": claims["email"], "sub": claims.get("sub")}


async def require_self_or_store_manager(
    user_id: UUID,
    user: _UserDict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
) -> UUID:
    """Allow users to manage their own profile, or managers of a shared store."""
    if _field(user, "id") == user_id:
        return user_id

    # Find stores the target user belongs to
    target_roles = db.collection_group("roles").where(
        "user_id", "==", str(user_id)
    ).stream()
    target_store_ids: set[UUID] = set()
    for rdoc in target_roles:
        store_ref = rdoc.reference.parent.parent
        if store_ref:
            target_store_ids.add(UUID(store_ref.id))

    if not target_store_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage this employee",
        )

    requester_roles = {
        _field(assignment, "store_id"): _field(assignment, "role")
        for assignment in _field(user, "store_roles", [])
    }
    for sid in target_store_ids:
        requester_role = _coerce_role(requester_roles.get(sid))
        if requester_role is None:
            continue
        if ROLE_HIERARCHY.get(requester_role, -1) >= ROLE_HIERARCHY[RoleEnum.manager]:
            return user_id

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to manage this employee",
    )
