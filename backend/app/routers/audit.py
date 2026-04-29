"""Owner-only audit log reader.

Exposes a paginated, filterable view over the Firestore `audit_events`
collection populated by `app.audit.log_event`. Read-only — there is no
endpoint for mutating audit records (that would defeat the point).

Authorization:
  Owner role at ANY store is required. Managers cannot read audit data
  because it contains password/role events about owners above them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from google.cloud import firestore
from pydantic import BaseModel

from app.audit import AUDIT_COLLECTION
from app.auth.dependencies import get_current_user
from app.firestore import get_firestore_db
from app.schemas.common import DataResponse

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditActor(BaseModel):
    user_id: Optional[str] = None
    email: Optional[str] = None
    uid: Optional[str] = None


class AuditRead(BaseModel):
    id: str
    event_type: str
    actor: AuditActor
    target: Optional[AuditActor] = None
    metadata: dict = {}
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: Optional[datetime] = None


class AuditPage(BaseModel):
    events: list[AuditRead]
    next_cursor: Optional[str] = None  # doc id to resume from


def _require_owner(user: dict) -> None:
    """Owner-at-any-store gate. Matches the precedent used elsewhere in the
    codebase for data-quality / vault pages."""
    for sr in user.get("store_roles", []):
        raw = sr.get("role")
        role = raw.value if hasattr(raw, "value") else str(raw or "")
        if role == "owner":
            return
    raise HTTPException(status_code=403, detail="Audit log is owner-only")


def _coerce_actor(raw) -> AuditActor:
    if not isinstance(raw, dict):
        return AuditActor()
    return AuditActor(
        user_id=raw.get("user_id"),
        email=raw.get("email"),
        uid=raw.get("uid"),
    )


@router.get("", response_model=DataResponse[AuditPage])
async def list_audit_events(
    event_type: Optional[str] = Query(None, description="Exact match on event_type (e.g. password.admin_reset)"),
    actor_email: Optional[str] = Query(None, description="Filter by actor email (exact match)"),
    target_email: Optional[str] = Query(None, description="Filter by target email (exact match)"),
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(None, description="Doc id from previous page's next_cursor"),
    user: dict = Depends(get_current_user),
):
    """Paginated, newest-first. Filters are ANDed. Cursor is the Firestore
    doc id of the last row from the previous page."""
    _require_owner(user)

    db = get_firestore_db()
    q = db.collection(AUDIT_COLLECTION).order_by(
        "created_at", direction=firestore.Query.DESCENDING
    )
    if event_type:
        q = q.where("event_type", "==", event_type)
    if actor_email:
        q = q.where("actor.email", "==", actor_email.lower())
    if target_email:
        q = q.where("target.email", "==", target_email.lower())

    # Cursor is a doc id; pass it through start_after. We fetch the cursor
    # snap first so Firestore gets the proper ordered-key anchor.
    if cursor:
        anchor = db.collection(AUDIT_COLLECTION).document(cursor).get()
        if anchor.exists:
            q = q.start_after(anchor)

    # +1 to detect "has more"
    snaps = list(q.limit(limit + 1).stream())
    has_more = len(snaps) > limit
    page = snaps[:limit]
    next_cursor = page[-1].id if has_more and page else None

    events: list[AuditRead] = []
    for snap in page:
        data = snap.to_dict() or {}
        ts = data.get("created_at")
        # Firestore returns tz-aware datetimes; Pydantic accepts these.
        events.append(AuditRead(
            id=snap.id,
            event_type=str(data.get("event_type") or ""),
            actor=_coerce_actor(data.get("actor")),
            target=_coerce_actor(data.get("target")) if data.get("target") else None,
            metadata=data.get("metadata") or {},
            ip=data.get("ip"),
            user_agent=data.get("user_agent"),
            created_at=ts if isinstance(ts, datetime) else None,
        ))

    return DataResponse(data=AuditPage(events=events, next_cursor=next_cursor))


@router.get("/event-types", response_model=DataResponse[list[str]])
async def list_event_types(user: dict = Depends(get_current_user)):
    """Return the static list of event_type values we write anywhere in the app.

    Using a curated list instead of a DISTINCT query because Firestore has no
    cheap distinct operator, and this list rarely changes. Keep in sync with
    `app/audit.py` callsites.
    """
    _require_owner(user)
    return DataResponse(data=[
        "password.self_change",
        "password.admin_reset",
        "password.policy_reject",
        "role.grant",
        "role.update",
        "role.revoke",
        "user.disable",
        "user.enable",
        "user.invite",
        "session.revoke_others",
        "auth.lockout",
        "webauthn.register",
        "webauthn.login",
        "webauthn.revoke",
    ])
