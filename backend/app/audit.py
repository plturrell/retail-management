"""Audit log helper.

Writes structured events to the Firestore `audit_events` collection so we have a
tamper-evident trail of password changes, role grants, account disables, etc. This
is what regulators / SOC auditors expect to see when they ask "who did what to
whom, and when?".

Design:
- Single function `log_event(...)` — synchronous Firestore write, called from
  inside the request handler after the privileged action succeeds. If the audit
  write itself fails we log a WARNING and swallow — we never fail the user-facing
  operation because audit couldn't be persisted.
- Server timestamps come from Firestore (`SERVER_TIMESTAMP`) so we don't trust the
  app clock.
- IP + user agent are captured when a Request is passed in, so we can correlate.
- Payloads are intentionally small — never include secrets (new passwords, tokens).

Schema of each audit_events doc:
  {
    "event_type":   "password.self_change" | "password.admin_reset" |
                    "role.grant" | "role.revoke" |
                    "user.disable" | "user.enable" |
                    "password.hibp_reject",
    "actor": {"user_id": "...", "email": "...", "uid": "..."},
    "target": {"user_id": "...", "email": "...", "uid": "..."} | None,
    "metadata": {...free-form, small...},
    "ip": "1.2.3.4" | None,
    "user_agent": "Mozilla/5.0..." | None,
    "created_at": <ServerTimestamp>,
  }
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from google.cloud import firestore
from starlette.requests import Request

from app.firestore import get_firestore_db

log = logging.getLogger(__name__)

AUDIT_COLLECTION = "audit_events"


def _actor_dict(actor: Any) -> dict[str, Any]:
    """Accepts the object `get_current_user` returns (has id/email/firebase_uid)."""
    if actor is None:
        return {}
    return {
        "user_id": getattr(actor, "id", None),
        "email":   getattr(actor, "email", None),
        "uid":     getattr(actor, "firebase_uid", None),
    }


def _target_dict(target: Any) -> Optional[dict[str, Any]]:
    if target is None:
        return None
    if isinstance(target, Mapping):
        return {
            "user_id": target.get("user_id") or target.get("id"),
            "email":   target.get("email"),
            "uid":     target.get("uid") or target.get("firebase_uid"),
        }
    return {
        "user_id": getattr(target, "id", None),
        "email":   getattr(target, "email", None),
        "uid":     getattr(target, "firebase_uid", None),
    }


def log_event(
    event_type: str,
    *,
    actor: Any = None,
    target: Any = None,
    metadata: Optional[dict[str, Any]] = None,
    request: Optional[Request] = None,
) -> None:
    """Write one audit_events document.

    Never raises — if Firestore is unavailable we log a warning and move on, so
    the caller's main operation isn't rolled back by audit failure. The tradeoff
    is that in a rare total-Firestore-outage we lose the audit line, which is
    acceptable for a 5-person retail ops team.
    """
    try:
        db = get_firestore_db()
        doc = {
            "event_type": event_type,
            "actor":  _actor_dict(actor),
            "target": _target_dict(target),
            "metadata": dict(metadata or {}),
            "ip": None,
            "user_agent": None,
            "created_at": firestore.SERVER_TIMESTAMP,
        }
        if request is not None:
            client = request.client
            doc["ip"] = (
                request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                or (client.host if client else None)
            )
            doc["user_agent"] = request.headers.get("user-agent")
        db.collection(AUDIT_COLLECTION).add(doc)
    except Exception as exc:  # noqa: BLE001 — audit must never break the request
        log.warning("audit log write failed for %s: %s", event_type, exc)
