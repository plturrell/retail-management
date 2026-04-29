"""Persisted history of CAG SFTP pushes + materialised remote errors.

Each successful or attempted push writes a row to ``cag_sftp_runs`` so the
owner UI can answer "did the 4pm cron actually run?" without SSH'ing into
the server. The companion ``cag_sftp_errors`` collection is populated by
:func:`sync_errors`, which reads the per-tenant ``Inbound/Error`` directory
and dedups entries by ``source_file`` + ``line``.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from app.services import cag_sftp

log = logging.getLogger(__name__)

RUN_COLLECTION = "cag_sftp_runs"
ERROR_COLLECTION = "cag_sftp_errors"


# ---------------------------------------------------------------------------
# Push history
# ---------------------------------------------------------------------------

def record_run(
    fs_db: Any,
    *,
    tenant_code: str,
    nec_store_id: str,
    taxable: bool,
    counts: dict[str, int],
    files_uploaded: list[str],
    bytes_uploaded: int,
    started_at: datetime,
    finished_at: datetime | None,
    errors: list[str],
    triggered_by: str = "",
    trigger_kind: str = "manual",
) -> str:
    """Persist a single push attempt. Returns the new doc id."""
    if fs_db is None:
        return ""
    doc_id = str(uuid.uuid4())
    ok = bool(files_uploaded) and not errors
    payload = {
        "id": doc_id,
        "tenant_code": tenant_code,
        "nec_store_id": nec_store_id,
        "taxable": bool(taxable),
        "counts": dict(counts or {}),
        "files_uploaded": list(files_uploaded or []),
        "bytes_uploaded": int(bytes_uploaded or 0),
        "errors": list(errors or []),
        "started_at": started_at.isoformat() if started_at else None,
        "finished_at": finished_at.isoformat() if finished_at else None,
        "triggered_by": triggered_by,
        "trigger_kind": trigger_kind,  # "manual" | "scheduled" | "test"
        "ok": ok,
        "created_at": datetime.now(timezone.utc),
    }
    try:
        fs_db.collection(RUN_COLLECTION).document(doc_id).set(payload)
    except Exception as exc:  # noqa: BLE001 - history is best-effort
        log.warning("Failed to persist CAG run %s: %s", doc_id, exc)
        return ""
    return doc_id


def list_runs(fs_db: Any, *, limit: int = 25) -> list[dict[str, Any]]:
    if fs_db is None:
        return []
    try:
        # Firestore doesn't allow descending without composite index in all
        # cases; we read all (capped at 500) and sort in memory.
        docs = list(fs_db.collection(RUN_COLLECTION).stream())
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to list CAG runs: %s", exc)
        return []
    rows = [d.to_dict() or {} for d in docs]
    rows.sort(key=lambda r: r.get("started_at") or r.get("created_at") or "", reverse=True)
    return rows[:limit]


# ---------------------------------------------------------------------------
# Error sync
# ---------------------------------------------------------------------------

def _error_key(source_file: str | None, line: int) -> str:
    return f"{source_file or '?'}::{line}"


def sync_errors(fs_db: Any, *, limit: int = 200) -> dict[str, int]:
    """Pull recent ``Inbound/Error`` entries via SFTP and upsert into Firestore.

    Returns ``{"fetched": N, "new": M, "skipped": K}``.
    """
    from app.services import cag_config  # local import to avoid cycle

    if fs_db is None:
        return {"fetched": 0, "new": 0, "skipped": 0}
    cfg = cag_config.load_config(fs_db).to_sftp_config()
    if not cag_sftp.is_configured(cfg):
        return {"fetched": 0, "new": 0, "skipped": 0}
    try:
        entries = cag_sftp.fetch_error_logs(config=cfg, limit=limit)
    except cag_sftp.SFTPConfigurationError as exc:
        log.warning("CAG error-sync skipped (not configured): %s", exc)
        return {"fetched": 0, "new": 0, "skipped": 0}
    except cag_sftp.SFTPTransportError as exc:
        log.warning("CAG error-sync transport error: %s", exc)
        return {"fetched": 0, "new": 0, "skipped": 0}

    coll = fs_db.collection(ERROR_COLLECTION)
    new_count = 0
    skipped = 0
    now = datetime.now(timezone.utc)
    for e in entries:
        key = _error_key(e.source_file, e.line)
        # Deterministic doc id avoids dupes on repeated syncs.
        doc_id = uuid.uuid5(uuid.NAMESPACE_URL, key).hex
        try:
            existing = coll.document(doc_id).get()
        except Exception:  # noqa: BLE001
            existing = None
        if existing is not None and getattr(existing, "exists", False):
            skipped += 1
            continue
        coll.document(doc_id).set(
            {
                "id": doc_id,
                "status": e.status,
                "line": e.line,
                "message": e.message,
                "source_file": e.source_file,
                "synced_at": now,
            }
        )
        new_count += 1
    return {"fetched": len(entries), "new": new_count, "skipped": skipped}


def list_errors(fs_db: Any, *, limit: int = 100) -> list[dict[str, Any]]:
    if fs_db is None:
        return []
    try:
        docs = list(fs_db.collection(ERROR_COLLECTION).stream())
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to list CAG errors: %s", exc)
        return []
    rows = [d.to_dict() or {} for d in docs]
    rows.sort(key=lambda r: r.get("synced_at") or "", reverse=True)
    return rows[:limit]


__all__ = [
    "ERROR_COLLECTION",
    "RUN_COLLECTION",
    "list_errors",
    "list_runs",
    "record_run",
    "sync_errors",
]
