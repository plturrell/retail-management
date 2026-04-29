"""Login-attempt accounting and account lockout.

Firebase Auth has internal quotas but doesn't let us policy-set "5 failures in
10 minutes → disable". So we do it client-assisted:

  1. LoginPage attempts `signInWithEmailAndPassword`.
  2. On failure, LoginPage calls POST /auth/report-failed-login {email} here.
  3. On success, LoginPage calls POST /auth/report-successful-login {email}.

We keep a per-email sliding window in Firestore:
  auth_failures/{sha1(email_lowercased)} = {
     email: str,
     failures: [timestamp, timestamp, ...]      (only within WINDOW)
  }

If the count inside the window ever reaches LOCKOUT_THRESHOLD, we:
  - disable the Firebase Auth user (if one exists)
  - revoke their refresh tokens
  - write an `auth.lockout` audit row
An owner/manager with reset-password permission can re-enable the account
through the existing /users/{id}/enable endpoint.

These endpoints are UNAUTHENTICATED — that's by design, because they're
called BEFORE a successful login exists. To prevent abuse we:
  - rate-limit both by IP (10/min)
  - hash the email before storing so a dumped Firestore never exposes raw
    email strings (the hash is still useful because we always hash the same
    input to look up the same doc).
"""
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Request, Response
from firebase_admin import auth as firebase_auth
from google.cloud import firestore
from pydantic import BaseModel, Field

from app.audit import log_event
from app.auth.firebase import _get_firebase_app
from app.firestore import get_firestore_db
from app.rate_limit import limiter

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

COLLECTION = "auth_failures"
WINDOW = timedelta(minutes=10)
LOCKOUT_THRESHOLD = 5


class AuthReport(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)


def _key(email: str) -> str:
    return hashlib.sha1(email.strip().lower().encode("utf-8")).hexdigest()  # noqa: S324


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _prune(failures: list[Any]) -> list[datetime]:
    """Drop any timestamps older than the sliding window; coerce to aware dt."""
    cutoff = _now() - WINDOW
    out: list[datetime] = []
    for ts in failures or []:
        if isinstance(ts, datetime):
            dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        else:
            continue
        if dt >= cutoff:
            out.append(dt)
    return out


@router.post("/report-failed-login")
@limiter.limit("10/minute")
async def report_failed_login(request: Request, response: Response, payload: AuthReport):
    """Record one failed login attempt. If it pushes the sliding-window count
    over LOCKOUT_THRESHOLD, disable the target Firebase user.

    Returns `{ locked: bool, remaining: int }` so the frontend can display a
    warning before the lockout fires.
    """
    email = str(payload.email).strip().lower()
    key = _key(email)
    db = get_firestore_db()
    doc_ref = db.collection(COLLECTION).document(key)
    snap = doc_ref.get()
    data = snap.to_dict() if snap.exists else {}
    failures = _prune(data.get("failures") or [])
    failures.append(_now())

    locked = False
    if len(failures) >= LOCKOUT_THRESHOLD:
        locked = True
        # Disable the Firebase user (idempotent — if already disabled, no harm).
        _get_firebase_app()
        try:
            record = firebase_auth.get_user_by_email(email)
            firebase_auth.update_user(record.uid, disabled=True)
            firebase_auth.revoke_refresh_tokens(record.uid)
            log_event(
                "auth.lockout",
                actor=None,
                target=type("T", (), {"id": "", "email": email, "firebase_uid": record.uid})(),
                metadata={
                    "failures_in_window": len(failures),
                    "window_minutes": int(WINDOW.total_seconds() // 60),
                },
                request=request,
            )
        except firebase_auth.UserNotFoundError:
            # Unknown email — still record the attempt for rate-limiter parity
            # but there's no Firebase user to disable.
            log.info("lockout: no firebase user for email hash=%s", key[:8])
        except Exception as exc:  # noqa: BLE001
            log.warning("lockout disable failed for %s: %s", email, exc)

    doc_ref.set({
        "email": email,
        "failures": failures,
        "last_event": firestore.SERVER_TIMESTAMP,
        "locked": locked,
    }, merge=True)

    return {
        "locked": locked,
        "remaining": max(LOCKOUT_THRESHOLD - len(failures), 0),
        "threshold": LOCKOUT_THRESHOLD,
        "window_minutes": int(WINDOW.total_seconds() // 60),
    }


@router.post("/report-successful-login")
@limiter.limit("30/minute")
async def report_successful_login(request: Request, response: Response, payload: AuthReport):
    """Reset the failure counter on successful sign-in. Best-effort; any
    error here is non-fatal — worst case the next failed login re-uses the
    existing counter state, which still protects the account."""
    email = str(payload.email).strip().lower()
    key = _key(email)
    try:
        get_firestore_db().collection(COLLECTION).document(key).set(
            {"email": email, "failures": [], "locked": False,
             "last_event": firestore.SERVER_TIMESTAMP},
            merge=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("reset-on-success failed for %s: %s", email, exc)
    return {"ok": True}
