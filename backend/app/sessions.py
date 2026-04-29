"""Session / sign-in tracking.

Commercial parity with Okta/Auth0/Clerk "where you're signed in" panels.
The source of truth is Firestore collection `auth_events` — every /users/me
hit (which the frontend fires once per app-shell mount, i.e. once per fresh
sign-in / token refresh) writes one document here.

We intentionally key sessions on a fingerprint of `(user_agent, ip_/24)`
instead of a random session id: Firebase Auth owns session state for real,
and we can't introspect its refresh-token fleet. This fingerprint is good
enough for a "you have 3 active devices, last seen yesterday" UI — not
a cryptographic session ledger.

Data shape (one doc per event):
    {
      "user_id": "...",
      "firebase_uid": "...",
      "fingerprint": "sha1(user_agent + ip_prefix)",
      "ip":      "1.2.3.4" | None,
      "user_agent": "Mozilla/5.0...",
      "created_at": <ServerTimestamp>,
    }

Reads:
  list_sessions(user_id) — aggregates by fingerprint, returns most-recent
  per fingerprint plus the first-seen timestamp. Capped at the last 100
  events (~months of activity for a single staff user).

Writes:
  record_signin(user_id, firebase_uid, request) — fire-and-forget; never
  raises. Safe to call from the /users/me handler.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from google.cloud import firestore
from starlette.requests import Request

from app.firestore import get_firestore_db

log = logging.getLogger(__name__)

AUTH_EVENTS = "auth_events"
_MAX_EVENTS_PER_USER = 100


def _ip_prefix(ip: Optional[str]) -> str:
    """Reduce to /24 (or /64 for IPv6) so a mobile user on a rotating DHCP lease
    doesn't show up as a new device every morning."""
    if not ip:
        return ""
    if ":" in ip:  # IPv6 — keep the first 4 groups
        return ":".join(ip.split(":")[:4])
    parts = ip.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3])
    return ip


def _fingerprint(user_agent: Optional[str], ip: Optional[str]) -> str:
    raw = f"{user_agent or ''}|{_ip_prefix(ip)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]  # noqa: S324 — non-cryptographic hash


def _extract(request: Request) -> tuple[Optional[str], Optional[str]]:
    try:
        ip = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else None)
        )
        ua = request.headers.get("user-agent")
    except Exception:  # noqa: BLE001
        return None, None
    return ip, ua


def record_signin(*, user_id: str, firebase_uid: str, request: Request) -> str:
    """Write one auth_events doc. Returns the fingerprint so the caller can
    decide whether to fire a "new device" notification."""
    try:
        ip, ua = _extract(request)
        fp = _fingerprint(ua, ip)
        db = get_firestore_db()
        db.collection(AUTH_EVENTS).add({
            "user_id": str(user_id),
            "firebase_uid": str(firebase_uid or ""),
            "fingerprint": fp,
            "ip": ip,
            "user_agent": ua,
            "created_at": firestore.SERVER_TIMESTAMP,
        })
        return fp
    except Exception as exc:  # noqa: BLE001
        log.warning("record_signin failed: %s", exc)
        return ""


def is_new_fingerprint(*, user_id: str, fingerprint: str) -> bool:
    """Return True iff this is the first time we've ever seen this
    fingerprint for this user. Used to fire the "new device signin" email."""
    if not fingerprint:
        return False
    try:
        db = get_firestore_db()
        # We just wrote one event with this fp; a "new" fingerprint means the
        # count is exactly 1 (our own fresh write).
        snaps = (
            db.collection(AUTH_EVENTS)
            .where("user_id", "==", str(user_id))
            .where("fingerprint", "==", fingerprint)
            .limit(2)
            .stream()
        )
        return sum(1 for _ in snaps) <= 1
    except Exception as exc:  # noqa: BLE001
        log.warning("is_new_fingerprint check failed: %s", exc)
        return False


def list_sessions(user_id: str) -> list[dict]:
    """Return a deduplicated, most-recent-first list of active fingerprints.

    One entry per distinct fingerprint with `first_seen` / `last_seen` / `count`.
    Any firebase_auth.revoke_refresh_tokens resets Firebase's own session
    state; this list is best-effort "devices we've observed" and doesn't
    distinguish still-valid from revoked sessions — that would require
    Firebase to expose token metadata, which it doesn't.
    """
    try:
        db = get_firestore_db()
        snaps = list(
            db.collection(AUTH_EVENTS)
            .where("user_id", "==", str(user_id))
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(_MAX_EVENTS_PER_USER)
            .stream()
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("list_sessions failed: %s", exc)
        return []

    by_fp: dict[str, dict] = {}
    for s in snaps:
        data = s.to_dict() or {}
        fp = data.get("fingerprint") or s.id
        ts = data.get("created_at")
        row = by_fp.setdefault(
            fp,
            {
                "fingerprint": fp,
                "ip": data.get("ip"),
                "user_agent": data.get("user_agent"),
                "first_seen": ts,
                "last_seen": ts,
                "count": 0,
            },
        )
        row["count"] += 1
        if ts and (row["first_seen"] is None or ts < row["first_seen"]):
            row["first_seen"] = ts
        if ts and (row["last_seen"] is None or ts > row["last_seen"]):
            row["last_seen"] = ts
        # Prefer the IP / UA from the most recent observation
        if ts == row["last_seen"]:
            row["ip"] = data.get("ip") or row["ip"]
            row["user_agent"] = data.get("user_agent") or row["user_agent"]

    rows = list(by_fp.values())
    rows.sort(key=lambda r: r["last_seen"] or 0, reverse=True)
    return rows
