import uuid as _uuid
from collections import defaultdict
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from firebase_admin import auth as firebase_auth
from google.cloud.firestore_v1.client import Client as FirestoreClient
from pydantic import BaseModel, Field

from app.audit import log_event
from app.email import (
    send_invite,
    send_new_device_signin,
    send_password_changed_self,
    send_password_reset_by_admin,
)
from app.sessions import (
    is_new_fingerprint,
    list_sessions,
    record_signin,
)
from app.auth.firebase import _get_firebase_app
from app.firestore import get_firestore_db
from app.firestore_helpers import (
    create_document,
    get_document,
    query_collection,
    update_document,
)
from app.auth.dependencies import (
    RoleEnum,
    ensure_store_role,
    ensure_system_admin,
    get_current_user,
    get_token_claims,
    is_system_admin,
    require_store_role,
)
from app.rate_limit import limiter
from app.security.password_policy import PasswordPolicyError, enforce as enforce_password_policy
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_to_read(data: dict) -> UserRead:
    """Convert a Firestore user dict to a UserRead schema."""
    return UserRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        firebase_uid=data.get("firebase_uid", ""),
        email=data.get("email", ""),
        full_name=data.get("full_name", ""),
        phone=data.get("phone"),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
        updated_at=data.get("updated_at"),
    )


def _role_to_read(data: dict) -> UserStoreRoleRead:
    """Convert a Firestore role dict to a UserStoreRoleRead schema."""
    return UserStoreRoleRead(
        id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id"),
        user_id=UUID(data["user_id"]) if isinstance(data.get("user_id"), str) else data.get("user_id"),
        store_id=UUID(data["store_id"]) if isinstance(data.get("store_id"), str) else data.get("store_id"),
        role=data.get("role", "staff"),
        created_at=data.get("created_at"),
    )


# ---------------------------------------------------------------------------
# Password / role helpers
# ---------------------------------------------------------------------------

_ROLE_RANK = {"staff": 1, "manager": 2, "owner": 3, "system_admin": 4}


def _role_name(sr: dict) -> str:
    """Coerce a role assignment's ``role`` field to its plain string value."""
    role = sr.get("role")
    return role.value if hasattr(role, "value") else (role or "")


def _caller_outranks_owner(caller: dict) -> bool:
    """True iff the caller is an owner or system_admin on any store.

    System admins bypass the per-store owner gate the way owners bypass the
    per-store manager gate; treating both uniformly here keeps the rest of
    the router free of string-list churn.
    """
    return any(
        _role_name(sr) in ("owner", "system_admin")
        for sr in caller.get("store_roles", [])
    )

# Firebase custom claim used to force password change on next sign-in (P1 #12).
# The frontend reads this via the ID token and blocks the app shell until the
# user visits /force-change-password. Cleared after a successful self-change.
_MUST_CHANGE_CLAIM = "must_change_password"


def _roles_for_user(user_id: UUID | str) -> list[dict]:
    """Return all store roles for a given user id across every store.

    Walks the `stores/*/roles/{user_id}` subcollections (needed for single-user
    lookups where we don't want to pay for a full collection_group scan).
    For bulk listing, prefer `_all_roles_grouped_by_user()` instead.
    """
    target_id = str(user_id)
    out: list[dict] = []
    for store_doc in query_collection("stores"):
        sid = store_doc.get("id")
        if not sid:
            continue
        role_doc = get_document(f"stores/{sid}/roles", target_id)
        if role_doc is not None:
            role_doc["store_id"] = sid
            out.append(role_doc)
    return out


def _all_roles_grouped_by_user(db: FirestoreClient) -> dict[str, list[dict]]:
    """Return `{user_id: [role_dict, ...]}` for the whole system in ONE query.

    Uses a Firestore `collection_group("roles")` query which transparently
    walks every `stores/*/roles/*` subcollection in a single RPC. This
    replaces the previous O(users × stores) nested loop in list_users —
    previously ~8.5k doc reads per page for 11 users × 770 store docs;
    now one query returning just the role docs that exist (~50 today).
    """
    grouped: dict[str, list[dict]] = defaultdict(list)
    for snap in db.collection_group("roles").stream():
        data = snap.to_dict() or {}
        # collection_group preserves the parent chain; the role doc lives at
        # stores/{store_id}/roles/{user_id}. Extract the store_id from the path
        # in case the stored payload is missing it (older seed-script writes).
        parent_store = snap.reference.parent.parent
        if parent_store is not None:
            data["store_id"] = parent_store.id
        uid = str(data.get("user_id") or snap.id)
        if uid:
            data.setdefault("id", snap.id)
            grouped[uid].append(data)
    return grouped


def _set_must_change_password(firebase_uid: str, value: bool) -> None:
    """Set or clear the force-password-change custom claim on the Firebase user.

    Preserves any other existing claims (role-based, tenant, etc) by merging
    rather than overwriting. The client must refresh its ID token for the new
    claim to take effect — we do that implicitly by revoking refresh tokens
    after a reset, which forces a re-login.
    """
    _get_firebase_app()
    try:
        record = firebase_auth.get_user(firebase_uid)
        claims = dict(record.custom_claims or {})
        if value:
            claims[_MUST_CHANGE_CLAIM] = True
        else:
            claims.pop(_MUST_CHANGE_CLAIM, None)
        firebase_auth.set_custom_user_claims(firebase_uid, claims or None)
    except Exception:  # noqa: BLE001 — claim-setting failure must not mask the password reset
        # Swallow; the audit log entry will still record the reset itself.
        pass


def _highest_role(store_roles: list[dict]) -> str:
    """Return 'owner' | 'manager' | 'staff' | '' — the strongest role found."""
    best = 0
    best_name = ""
    for r in store_roles:
        raw = r.get("role")
        name = raw.value if hasattr(raw, "value") else str(raw or "")
        rank = _ROLE_RANK.get(name, 0)
        if rank > best:
            best = rank
            best_name = name
    return best_name


def _can_reset_password(caller: dict, target_user_id: str, target_roles: list[dict]) -> tuple[bool, str]:
    """Permission matrix for admin password reset.

    - You cannot reset your own password via this endpoint (use change-password).
    - Owners can reset any user (including other owners).
    - Managers can reset managers/staff at stores where the manager has a manager role.
    - Managers cannot reset owner accounts.
    - Staff-only users can never reset anyone.
    Returns (allowed, reason).
    """
    caller_id = str(caller.get("id") or "")
    if caller_id and caller_id == str(target_user_id):
        return False, "Use /users/me/change-password for your own password"

    caller_is_owner = _caller_outranks_owner(caller)
    if caller_is_owner:
        return True, ""

    target_highest = _highest_role(target_roles)
    if target_highest == "owner":
        return False, "Only owners can reset an owner's password"

    # Manager: must share a store with the target where caller has manager role.
    caller_manager_stores: set[str] = set()
    for sr in caller.get("store_roles", []):
        role_name = sr.get("role").value if hasattr(sr.get("role"), "value") else sr.get("role")
        if role_name == "manager":
            caller_manager_stores.add(str(sr.get("store_id")))
    target_stores = {str(r.get("store_id")) for r in target_roles if r.get("store_id")}
    if caller_manager_stores and (caller_manager_stores & target_stores):
        return True, ""

    return False, "You don't have permission to reset this user's password"


def _find_role_assignment(user: dict, role_id: UUID) -> tuple[dict, str] | None:
    target_role_id = str(role_id)
    for store_role in user.get("store_roles", []):
        store_id = store_role.get("store_id")
        if store_id is None:
            continue
        role_path = f"stores/{store_id}/roles"
        for role_doc in query_collection(role_path):
            if str(role_doc.get("id")) != target_role_id:
                continue
            role_doc["store_id"] = str(store_id)
            doc_id = str(role_doc.get("user_id") or role_doc.get("id"))
            return role_doc, doc_id
    return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/me", response_model=DataResponse[UserMeRead])
async def get_current_user_profile(
    request: Request,
    user: dict = Depends(get_current_user),
):
    # Track this sign-in as a "session observation" so the Profile > Active
    # Devices panel has data, and so we can email the user on first-seen device.
    user_id = str(user.get("id") or "")
    firebase_uid = str(user.get("firebase_uid") or "")
    if user_id:
        fp = record_signin(user_id=user_id, firebase_uid=firebase_uid, request=request)
        if fp and is_new_fingerprint(user_id=user_id, fingerprint=fp):
            ip, ua = _client_meta(request)
            email = (user.get("email") or "").strip()
            if email:
                send_new_device_signin(
                    to=email,
                    display_name=user.get("full_name"),
                    ip=ip,
                    user_agent=ua,
                    when=datetime.now(timezone.utc).isoformat(timespec="minutes"),
                )

    # Build store_roles for UserMeRead
    store_roles = []
    for sr in user.get("store_roles", []):
        store_roles.append(
            UserStoreRoleRead(
                id=UUID(sr["id"]) if isinstance(sr.get("id"), str) else sr.get("id", _uuid.uuid4()),
                user_id=UUID(sr["user_id"]) if isinstance(sr.get("user_id"), str) else sr.get("user_id"),
                store_id=UUID(sr["store_id"]) if isinstance(sr.get("store_id"), str) else sr.get("store_id"),
                role=sr.get("role").value if hasattr(sr.get("role"), "value") else sr.get("role", "staff"),
                created_at=sr.get("created_at"),
            )
        )
    me = UserMeRead(
        id=UUID(user["id"]) if isinstance(user.get("id"), str) else user.get("id"),
        firebase_uid=user.get("firebase_uid", ""),
        email=user.get("email", ""),
        full_name=user.get("full_name", ""),
        phone=user.get("phone"),
        created_at=user.get("created_at", datetime.now(timezone.utc)),
        updated_at=user.get("updated_at"),
        store_roles=store_roles,
    )
    return DataResponse(data=me)


class SessionRead(BaseModel):
    fingerprint: str
    ip: str | None = None
    user_agent: str | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    count: int = 0


@router.get("/me/sessions", response_model=DataResponse[list[SessionRead]])
async def list_my_sessions(user: dict = Depends(get_current_user)):
    """List the devices / networks this user has signed in from recently.

    Aggregated from `auth_events` (written every time the frontend fetches
    `/users/me`, i.e. roughly once per sign-in / page reload). Not a
    cryptographic session ledger — Firebase owns real session state — but
    matches the "Where you're logged in" panels users expect.
    """
    user_id = str(user.get("id") or "")
    rows = list_sessions(user_id) if user_id else []
    return DataResponse(data=[SessionRead(**r) for r in rows])


@router.post("/me/sign-out-other-devices")
async def sign_out_other_devices(
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Nuke every refresh token for the current user.

    Firebase doesn't let us revoke individual tokens — it's all-or-nothing —
    so this endpoint signs out ALL devices including the caller's. The
    caller's existing ID token stays valid until expiry (~1h), at which
    point the frontend will bounce them back to the login screen. This is
    still strictly better than doing nothing and leaves the user no worse
    off than re-logging in once.
    """
    uid = user.get("firebase_uid")
    if not uid:
        raise HTTPException(status_code=400, detail="No firebase_uid on current user")
    _get_firebase_app()
    try:
        firebase_auth.revoke_refresh_tokens(uid)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not revoke tokens: {e}") from e
    log_event(
        "session.revoke_others",
        actor=_actor_obj(user),
        target=_actor_obj(user),
        request=request,
    )
    return {"message": "All other devices have been signed out. You'll be signed out too when this session's token expires."}


@router.post("", response_model=DataResponse[UserRead], status_code=201)
async def create_user(
    payload: UserCreate,
    claims: dict = Depends(get_token_claims),
    db: FirestoreClient = Depends(get_firestore_db),
):
    if claims.get("uid") != payload.firebase_uid:
        raise HTTPException(
            status_code=403,
            detail="Authenticated users may only create their own user record",
        )

    existing = query_collection(
        "users",
        filters=[("firebase_uid", "==", payload.firebase_uid)],
        limit=1,
    )
    if existing:
        raise HTTPException(status_code=409, detail="User already exists")

    now = datetime.now(timezone.utc)
    user_id = str(_uuid.uuid4())
    doc_data = payload.model_dump()
    doc_data["id"] = user_id
    doc_data["created_at"] = now
    doc_data["updated_at"] = now

    created = create_document("users", doc_data, doc_id=user_id)
    return DataResponse(data=_user_to_read(created))


@router.patch("/me", response_model=DataResponse[UserRead])
async def update_current_user(
    payload: UserUpdate,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    updates = payload.model_dump(exclude_unset=True)
    if updates:
        updates["updated_at"] = datetime.now(timezone.utc)
        updated = update_document("users", str(user["id"]), updates)
    else:
        updated = user
    return DataResponse(data=_user_to_read(updated))


@router.post("/roles", response_model=DataResponse[UserStoreRoleRead], status_code=201)
async def assign_store_role(
    request: Request,
    payload: UserStoreRoleCreate,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    ensure_store_role(user, payload.store_id, RoleEnum.owner)

    # Verify target user exists
    target_user = get_document("users", str(payload.user_id))
    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Check for existing role in stores/{store_id}/roles/{user_id}
    role_path = f"stores/{payload.store_id}/roles"
    existing = get_document(role_path, str(payload.user_id))
    if existing is not None:
        raise HTTPException(status_code=409, detail="User already has a role for this store")

    role_id = str(_uuid.uuid4())
    now = datetime.now(timezone.utc)
    role_data = {
        "id": role_id,
        "user_id": str(payload.user_id),
        "store_id": str(payload.store_id),
        "role": payload.role,
        "created_at": now,
    }
    create_document(role_path, role_data, doc_id=str(payload.user_id))

    log_event(
        "role.grant",
        actor=_actor_obj(user),
        target=_actor_obj(target_user),
        metadata={
            "store_id": str(payload.store_id),
            "role": payload.role.value if hasattr(payload.role, "value") else str(payload.role),
        },
        request=request,
    )

    return DataResponse(data=_role_to_read(role_data))


@router.patch("/roles/{role_id}", response_model=DataResponse[UserStoreRoleRead])
async def update_store_role(
    request: Request,
    role_id: UUID,
    payload: UserStoreRoleUpdate,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    role_match = _find_role_assignment(user, role_id)
    if role_match is None:
        raise HTTPException(status_code=404, detail="Role assignment not found")

    role_data, doc_id = role_match
    store_id = UUID(str(role_data["store_id"]))

    ensure_store_role(user, store_id, RoleEnum.owner)

    try:
        new_role = RoleEnum(payload.role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid role: {payload.role}")

    old_role = role_data.get("role")
    old_role = old_role.value if hasattr(old_role, "value") else str(old_role or "")

    updated = update_document(
        f"stores/{store_id}/roles",
        doc_id,
        {"role": new_role.value},
    )

    target_user = get_document("users", str(role_data.get("user_id") or doc_id)) or {}
    log_event(
        "role.update",
        actor=_actor_obj(user),
        target=_actor_obj(target_user),
        metadata={
            "store_id": str(store_id),
            "old_role": old_role,
            "new_role": new_role.value,
        },
        request=request,
    )
    return DataResponse(data=_role_to_read(updated))


@router.delete("/roles/{role_id}", status_code=204)
async def remove_store_role(
    request: Request,
    role_id: UUID,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    role_match = _find_role_assignment(user, role_id)
    if role_match is None:
        raise HTTPException(status_code=404, detail="Role assignment not found")

    role_data, doc_id = role_match
    store_id = UUID(str(role_data["store_id"]))

    ensure_store_role(user, store_id, RoleEnum.owner)

    user_id_str = role_data.get("user_id", "")
    if user_id_str == str(user.get("id")):
        raise HTTPException(status_code=400, detail="Cannot remove your own role")

    from app.firestore_helpers import delete_document

    delete_document(f"stores/{store_id}/roles", doc_id)

    target_user = get_document("users", str(user_id_str) or doc_id) or {}
    old_role = role_data.get("role")
    old_role = old_role.value if hasattr(old_role, "value") else str(old_role or "")
    log_event(
        "role.revoke",
        actor=_actor_obj(user),
        target=_actor_obj(target_user),
        metadata={"store_id": str(store_id), "role": old_role},
        request=request,
    )


@router.get("/search", response_model=DataResponse[list[UserRead]])
async def search_users(
    email: str,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    # Firestore doesn't support ILIKE — use range query for prefix match
    results = query_collection(
        "users",
        filters=[
            ("email", ">=", email.lower()),
            ("email", "<=", email.lower() + "\uf8ff"),
        ],
        limit=10,
    )
    deduped: dict[str, dict] = {}
    for result in results:
        email_key = str(result.get("email", "")).lower()
        dedupe_key = email_key or str(result.get("id"))
        deduped.setdefault(dedupe_key, result)
    return DataResponse(data=[_user_to_read(u) for u in deduped.values()])


# ---------------------------------------------------------------------------
# Password management endpoints
# ---------------------------------------------------------------------------

class ChangePasswordRequest(BaseModel):
    # Minimum is enforced both here (fast Pydantic reject) and by the
    # password_policy module (real breach check). Keeping the Pydantic min_length
    # at 10 matches MIN_LEN in app.security.password_policy.
    new_password: str = Field(..., min_length=10, max_length=64, description="New password (≥10 chars)")


class ResetPasswordResponse(BaseModel):
    user_id: UUID
    email: str
    reset_link: str
    expires_in_seconds: int
    message: str


class DisableUserResponse(BaseModel):
    user_id: UUID
    email: str
    disabled: bool
    message: str


class UserWithRolesRead(BaseModel):
    id: UUID
    email: str
    full_name: str
    firebase_uid: str
    disabled: bool = False
    must_change_password: bool = False
    highest_role: str  # 'owner' | 'manager' | 'staff' | ''
    store_codes: list[str]


@router.post("/me/change-password")
@limiter.limit("5/hour")
async def change_my_password(
    request: Request,  # required by slowapi to resolve the rate limit key
    body: ChangePasswordRequest,
    user: dict = Depends(get_current_user),
):
    """Self-service password change. Requires a valid Firebase JWT.

    The incoming JWT already proves identity, so we don't require the old
    password on this endpoint — the frontend MUST call
    `reauthenticateWithCredential` before hitting us, which gives the true
    "prove you know the current password" check.

    This endpoint additionally:
      - enforces the password policy (length + HIBP breach check)
      - revokes all refresh tokens so other devices re-authenticate
      - clears the force-change-password custom claim if it was set
      - writes an audit_events row
    Rate limit: 5/hour per IP (plus Firebase's own internal limits).
    """
    uid = user.get("firebase_uid")
    if not uid:
        raise HTTPException(status_code=400, detail="Current user has no firebase_uid")

    # 1. Policy (fast-fail; the client-side length check is UX only, this is the gate)
    try:
        enforce_password_policy(body.new_password)
    except PasswordPolicyError as e:
        log_event(
            "password.policy_reject",
            actor=_actor_obj(user),
            metadata={"reason": str(e)},
            request=request,
        )
        raise HTTPException(status_code=400, detail=str(e))

    # 2. Apply in Firebase Auth (Admin SDK — server-side, authoritative)
    _get_firebase_app()
    try:
        firebase_auth.update_user(uid, password=body.new_password)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not update password: {e}")

    # 3. Revoke refresh tokens so existing sessions on other devices die.
    #    The user's CURRENT session will also get a token expiry; the FE will
    #    fetch a fresh ID token on next request which is fine.
    try:
        firebase_auth.revoke_refresh_tokens(uid)
    except Exception:  # noqa: BLE001 — non-fatal; password is already rotated
        pass

    # 4. Clear the "must change on next login" claim, if set.
    _set_must_change_password(uid, False)

    # 5. Audit (best-effort; never raises)
    log_event(
        "password.self_change",
        actor=_actor_obj(user),
        target=_actor_obj(user),
        metadata={"method": "jwt_reauth"},
        request=request,
    )

    # 6. Courtesy email so the user sees a silent change immediately.
    email = (user.get("email") or "").strip()
    if email:
        ip, ua = _client_meta(request)
        send_password_changed_self(
            to=email,
            display_name=user.get("full_name"),
            ip=ip,
            user_agent=ua,
        )

    return {"message": "Password updated. Other sessions on other devices have been signed out."}


@router.post("/{user_id}/reset-password", response_model=ResetPasswordResponse)
@limiter.limit("20/hour")
async def admin_reset_password(
    request: Request,  # slowapi
    user_id: UUID,
    caller: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Admin resets another user's password — via a time-bounded reset LINK.

    Commercial security pattern (Okta/Auth0/Firebase Console):
      - We do NOT set a plaintext password on the user's behalf; that would
        mean plaintext-over-Slack, screenshots, terminal scrollback, etc.
      - Instead we generate a Firebase-native password-reset link that is
        valid for ~1 hour, usable exactly once, and expires on use.
      - The admin shares the link with the user (email, SMS, in-person).
      - We flag the target with `must_change_password` so if they somehow
        sign in before clicking the link, the UI still forces a reset.
      - We revoke all their refresh tokens so any active session is kicked.
      - Everything is audited.

    Permission matrix (see _can_reset_password):
      - Owners can reset anyone (including other owners)
      - Managers can reset staff/managers at stores they manage
      - Nobody can reset their own password here (use /me/change-password)
    """
    target = get_document("users", str(user_id))
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    target_roles = _roles_for_user(user_id)
    allowed, reason = _can_reset_password(caller, str(user_id), target_roles)
    if not allowed:
        raise HTTPException(status_code=403, detail=reason)

    firebase_uid = target.get("firebase_uid")
    target_email = (target.get("email") or "").strip()
    if not firebase_uid or not target_email:
        raise HTTPException(status_code=400, detail="Target user has no firebase_uid or email")

    _get_firebase_app()

    # 1. Generate the reset link. Default TTL is 1 hour per Firebase spec.
    try:
        reset_link = firebase_auth.generate_password_reset_link(target_email)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not generate reset link: {e}")

    # 2. Revoke refresh tokens so any active session on any device is invalidated.
    try:
        firebase_auth.revoke_refresh_tokens(firebase_uid)
    except Exception:  # noqa: BLE001 — non-fatal
        pass

    # 3. Flag the user so the UI forces a reset even if they sneak in another way.
    _set_must_change_password(firebase_uid, True)

    # 4. Audit
    log_event(
        "password.admin_reset",
        actor=_actor_obj(caller),
        target=_actor_obj(target),
        metadata={"target_role": _highest_role(target_roles)},
        request=request,
    )

    # 5. Email the reset link directly to the user so the admin doesn't have
    #    to ferry a sensitive string through Slack/SMS/etc. When SendGrid
    #    isn't wired in, this goes to the ConsoleBackend (server logs only),
    #    and the admin UI still shows the link as a fallback.
    send_password_reset_by_admin(
        to=target_email,
        display_name=target.get("full_name"),
        admin_email=(caller.get("email") or "an admin"),
        reset_link=reset_link,
    )

    return ResetPasswordResponse(
        user_id=user_id,
        email=target_email,
        reset_link=reset_link,
        expires_in_seconds=3600,
        message="Reset link generated and emailed. Share again via a secure channel if needed — it expires in ~1 hour and works once.",
    )


@router.post("/{user_id}/disable", response_model=DisableUserResponse)
async def disable_user(
    request: Request,
    user_id: UUID,
    caller: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Soft-disable a user's Firebase Auth account.

    Keeps the Firestore user doc and role assignments intact so audit trails
    and payroll history still resolve, but sets `disabled=True` in Firebase
    Auth and revokes refresh tokens — the user can't sign in. Reversible via
    /enable.

    Authorization: system_admin only. Locking another user out is a
    high-impact, attacker-friendly action (mass-disable would lock owners
    and managers out of every store) so it sits above the owner tier.
    """
    ensure_system_admin(caller)

    target = get_document("users", str(user_id))
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    if str(caller.get("id") or "") == str(user_id):
        raise HTTPException(status_code=400, detail="You cannot disable your own account")

    firebase_uid = target.get("firebase_uid")
    if not firebase_uid:
        raise HTTPException(status_code=400, detail="Target user has no firebase_uid")

    _get_firebase_app()
    try:
        firebase_auth.update_user(firebase_uid, disabled=True)
        firebase_auth.revoke_refresh_tokens(firebase_uid)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not disable user: {e}")

    log_event(
        "user.disable",
        actor=_actor_obj(caller),
        target=_actor_obj(target),
        request=request,
    )
    return DisableUserResponse(
        user_id=user_id,
        email=target.get("email", ""),
        disabled=True,
        message="Account disabled. Refresh tokens revoked.",
    )


@router.post("/{user_id}/enable", response_model=DisableUserResponse)
async def enable_user(
    request: Request,
    user_id: UUID,
    caller: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Re-enable a previously disabled user. system_admin only."""
    ensure_system_admin(caller)

    target = get_document("users", str(user_id))
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    firebase_uid = target.get("firebase_uid")
    if not firebase_uid:
        raise HTTPException(status_code=400, detail="Target user has no firebase_uid")

    _get_firebase_app()
    try:
        firebase_auth.update_user(firebase_uid, disabled=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not enable user: {e}")

    log_event(
        "user.enable",
        actor=_actor_obj(caller),
        target=_actor_obj(target),
        request=request,
    )
    return DisableUserResponse(
        user_id=user_id,
        email=target.get("email", ""),
        disabled=False,
        message="Account re-enabled.",
    )


class InviteRequest(BaseModel):
    email: str = Field(..., description="Email address of the person to invite")
    full_name: str = Field("", description="Display name; defaults to email local-part")
    role: str = Field(..., description="'staff' | 'manager' | 'owner' | 'system_admin'")
    store_ids: list[UUID] = Field(default_factory=list, description="Stores to grant the role at")


class InviteResponse(BaseModel):
    user_id: UUID
    email: str
    setup_link: str
    expires_in_seconds: int
    email_sent: bool
    message: str


@router.post("/invite", response_model=InviteResponse, status_code=201)
async def invite_user(
    request: Request,
    payload: InviteRequest,
    caller: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Create a new user and send them a first-time sign-in link.

    Replaces the old ad-hoc `seed_users.py` workflow for anything that
    happens post-launch. The invited user:
      1. Gets a Firebase Auth account with a random unusable password.
      2. Gets a Firestore `users/{id}` document.
      3. Gets role assignments at each requested store.
      4. Is flagged with `must_change_password=true` so even if the link
         falls into the wrong hands and somehow completes, the first post-
         setup navigation bounces them through `/force-change-password`.
      5. Is emailed a one-time password-setup link.

    Permissions:
      - Any manager or owner can invite a 'staff' user at stores they manage.
      - Only owners can invite 'manager' or 'owner' users, and owners can
        invite at any store.
      - Only existing system admins can invite 'system_admin'. The role grant
        is written at the requested stores; ``is_system_admin`` then matches
        on any such assignment to bypass per-store membership checks.
      - Inviting `email` that already exists in Firebase is refused — use
        /users/{id}/reset-password for password recovery on existing users.
    """
    caller_is_owner = _caller_outranks_owner(caller)
    caller_is_admin = is_system_admin(caller)
    target_role = payload.role.lower().strip()
    if target_role not in {"staff", "manager", "owner", "system_admin"}:
        raise HTTPException(status_code=400, detail=f"Invalid role: {payload.role}")
    if target_role in {"manager", "owner"} and not caller_is_owner:
        raise HTTPException(status_code=403, detail="Only owners can invite managers or owners")
    if target_role == "system_admin" and not caller_is_admin:
        raise HTTPException(status_code=403, detail="Only system admins can grant the system_admin role")
    if target_role == "system_admin" and not payload.store_ids:
        raise HTTPException(status_code=400, detail="system_admin grants require at least one store assignment")

    # For staff invites by a manager: every requested store must be a store
    # the caller manages. Owners get a free pass (they invite anywhere).
    if not caller_is_owner:
        manager_stores: set[str] = set()
        for sr in caller.get("store_roles", []):
            name = sr.get("role").value if hasattr(sr.get("role"), "value") else sr.get("role")
            if name == "manager":
                manager_stores.add(str(sr.get("store_id")))
        requested = {str(s) for s in payload.store_ids}
        foreign = requested - manager_stores
        if foreign:
            raise HTTPException(
                status_code=403,
                detail=f"You don't manage stores: {sorted(foreign)}",
            )

    email = payload.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email required")
    display_name = (payload.full_name or "").strip() or email.split("@")[0].title()

    _get_firebase_app()

    # Refuse overwrite — existing users must go through reset-password.
    try:
        firebase_auth.get_user_by_email(email)
        raise HTTPException(status_code=409, detail="That email already has an account. Use reset-password instead.")
    except firebase_auth.UserNotFoundError:
        pass
    except HTTPException:
        raise

    # 1. Firebase Auth user with an unknown random password — the invitee never
    #    sees it; they'll set a real one via the reset-link flow.
    import secrets as _secrets
    import string as _string
    throwaway = "".join(_secrets.choice(_string.ascii_letters + _string.digits) for _ in range(32))
    try:
        record = firebase_auth.create_user(
            email=email,
            password=throwaway,
            display_name=display_name,
            email_verified=False,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not create Firebase user: {e}") from e
    firebase_uid = record.uid

    # 2. Firestore user doc.
    user_id = str(_uuid.uuid4())
    now = datetime.now(timezone.utc)
    create_document(
        "users",
        {
            "id": user_id,
            "firebase_uid": firebase_uid,
            "email": email,
            "full_name": display_name,
            "phone": None,
            "created_at": now,
            "updated_at": now,
        },
        doc_id=user_id,
    )

    # 3. Role grants at each requested store.
    granted_store_codes: list[str] = []
    for store_uuid in payload.store_ids:
        store_id = str(store_uuid)
        existing = get_document(f"stores/{store_id}/roles", user_id)
        if existing:
            continue  # already granted; idempotent
        create_document(
            f"stores/{store_id}/roles",
            {
                "id": str(_uuid.uuid4()),
                "user_id": user_id,
                "store_id": store_id,
                "role": target_role,
                "created_at": now,
            },
            doc_id=user_id,
        )
        # Lookup store_code for the invite email (best-effort).
        store_doc = get_document("stores", store_id) or {}
        code = store_doc.get("store_code")
        if code:
            granted_store_codes.append(code)

    # 4. Force password change on first login.
    _set_must_change_password(firebase_uid, True)

    # 5. Password setup link.
    try:
        setup_link = firebase_auth.generate_password_reset_link(email)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not generate setup link: {e}") from e

    # 6. Invite email.
    email_ok = True
    try:
        send_invite(
            to=email,
            display_name=display_name,
            inviter_email=(caller.get("email") or "an admin"),
            setup_link=setup_link,
            role=target_role,
            stores=granted_store_codes,
        )
    except Exception:  # noqa: BLE001
        email_ok = False

    # 7. Audit.
    log_event(
        "user.invite",
        actor=_actor_obj(caller),
        target=_actor_obj({"id": user_id, "email": email, "firebase_uid": firebase_uid}),
        metadata={
            "role": target_role,
            "store_ids": [str(s) for s in payload.store_ids],
        },
        request=request,
    )

    return InviteResponse(
        user_id=UUID(user_id),
        email=email,
        setup_link=setup_link,
        expires_in_seconds=3600,
        email_sent=email_ok,
        message=(
            "Invite created. An email with the setup link has been sent." if email_ok else
            "Invite created, but the email could not be sent. Share the setup link manually."
        ),
    )


@router.get("", response_model=DataResponse[list[UserWithRolesRead]])
async def list_users(
    caller: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """List users visible to the caller.

    - Owners: everyone
    - Managers: users with any role at a store where the caller is manager
    - Staff-only: only themselves

    Performance: uses `collection_group("roles")` for a single Firestore RPC
    instead of the old O(users × stores) nested loop — see
    `_all_roles_grouped_by_user` for details.
    """
    caller_store_roles = caller.get("store_roles", [])
    caller_is_owner = _caller_outranks_owner(caller)
    caller_manager_stores: set[str] = set()
    for sr in caller_store_roles:
        if _role_name(sr) == "manager":
            caller_manager_stores.add(str(sr.get("store_id")))

    # One query for ALL role docs across all stores.
    roles_by_user = _all_roles_grouped_by_user(db)

    # Pre-index store_id -> store_code for display.
    store_code_by_id: dict[str, str] = {}
    for s in query_collection("stores"):
        sid = s.get("id")
        code = s.get("store_code")
        if sid and code:
            store_code_by_id[str(sid)] = code

    # Pre-fetch Firebase Auth user records in a single batched request so we
    # can display the `disabled` flag and `must_change_password` claim without
    # N extra round-trips. Capped at the Firebase batch limit of 100.
    _get_firebase_app()
    fb_meta: dict[str, dict] = {}
    all_users_raw = query_collection("users")
    uids = [u.get("firebase_uid") for u in all_users_raw if u.get("firebase_uid")]
    if uids:
        try:
            result = firebase_auth.get_users(
                [firebase_auth.UidIdentifier(u) for u in uids[:100]]
            )
            for rec in result.users:
                fb_meta[rec.uid] = {
                    "disabled": bool(rec.disabled),
                    "must_change_password": bool((rec.custom_claims or {}).get(_MUST_CHANGE_CLAIM)),
                }
        except Exception:  # noqa: BLE001
            pass  # fall through with empty fb_meta; list still works, flags just default

    results: list[UserWithRolesRead] = []
    for u in all_users_raw:
        uid = str(u.get("id") or "")
        if not uid:
            continue
        target_roles = roles_by_user.get(uid, [])
        target_store_ids = {str(r.get("store_id")) for r in target_roles}

        visible = False
        if caller_is_owner:
            visible = True
        elif caller_manager_stores and (caller_manager_stores & target_store_ids):
            visible = True
        elif uid == str(caller.get("id")):
            visible = True
        if not visible:
            continue

        meta = fb_meta.get(u.get("firebase_uid", ""), {})
        results.append(UserWithRolesRead(
            id=UUID(uid),
            email=u.get("email", ""),
            full_name=u.get("full_name", ""),
            firebase_uid=u.get("firebase_uid", ""),
            disabled=meta.get("disabled", False),
            must_change_password=meta.get("must_change_password", False),
            highest_role=_highest_role(target_roles),
            store_codes=sorted(
                {store_code_by_id.get(sid, "") for sid in target_store_ids if store_code_by_id.get(sid)}
            ),
        ))
    # Sort: owners first, then managers, then staff, alphabetical by email within a tier.
    results.sort(key=lambda r: (-_ROLE_RANK.get(r.highest_role, 0), r.email.lower()))
    return DataResponse(data=results)


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    """Extract (ip, user_agent) from the Starlette request. Mirrors the logic
    in `app.audit.log_event` so audit rows and notification emails always see
    the same client-identifying data."""
    try:
        ip = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else None)
        )
        ua = request.headers.get("user-agent")
    except Exception:  # noqa: BLE001
        return None, None
    return ip, ua


def _actor_obj(user_dict: dict):
    """Wrap a Firestore user dict into a simple object with id/email/firebase_uid
    attributes, so `audit.log_event` can read them uniformly (it accepts either
    an attr-object or a Mapping, but the Mapping path expects string keys only)."""
    class _A:  # noqa: N801
        id = str(user_dict.get("id") or "")
        email = str(user_dict.get("email") or "")
        firebase_uid = str(user_dict.get("firebase_uid") or "")
    return _A()


@router.get(
    "/stores/{store_id}/employees",
    response_model=PaginatedResponse[StoreEmployeeRead],
)
async def list_store_employees(
    store_id: UUID,
    _: dict = Depends(require_store_role(RoleEnum.manager)),
    db: FirestoreClient = Depends(get_firestore_db),
):
    # Query roles for this store
    role_path = f"stores/{store_id}/roles"
    role_docs = query_collection(role_path)

    employees = []
    for r in role_docs:
        uid = r.get("user_id", r.get("id"))
        user_data = get_document("users", str(uid))
        if user_data is None:
            continue
        employees.append(
            StoreEmployeeRead(
                id=UUID(user_data["id"]) if isinstance(user_data.get("id"), str) else user_data.get("id"),
                role_id=UUID(r["id"]) if isinstance(r.get("id"), str) else r.get("id", _uuid.uuid4()),
                full_name=user_data.get("full_name", ""),
                email=user_data.get("email", ""),
                phone=user_data.get("phone"),
                role=r.get("role", "staff"),
            )
        )

    return PaginatedResponse(
        data=employees,
        total=len(employees),
        page=1,
        page_size=len(employees),
    )
