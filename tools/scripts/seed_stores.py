#!/usr/bin/env python3
"""
Provision the canonical store records.

Creates (idempotently) the five Victoria Enso store documents in Firestore:
TAKA-01, ISETAN-01, JEWEL-01, BREEZE-01 (HQ/warehouse), ONLINE-01.

`seed_users.py` looks up stores by ``store_code`` when granting per-store
roles. Run this script first (once per environment) so those lookups
resolve.

Usage:
  # Dry-run (default) — shows what would happen, no writes
  python tools/scripts/seed_stores.py

  # Apply changes
  python tools/scripts/seed_stores.py --apply
"""
from __future__ import annotations

import argparse
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import firebase_admin
from firebase_admin import firestore


PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "victoriaensoapp")


# ── Stores ───────────────────────────────────────────────────────────────────

STORES: list[dict[str, Any]] = [
    {
        "store_code": "TAKA-01",
        "name": "VictoriaEnso – Takashimaya",
        "location": "Takashimaya Shopping Centre",
        "address": "391 Orchard Rd, #B1-13, Singapore 238872",
        "is_active": True,
    },
    {
        "store_code": "ISETAN-01",
        "name": "VictoriaEnso – Isetan Scotts",
        "location": "Isetan Scotts",
        "address": "350 Orchard Road, Shaw House, Singapore 238868",
        "is_active": True,
    },
    {
        "store_code": "JEWEL-01",
        "name": "VictoriaEnso – Jewel Changi",
        "location": "Jewel Changi Airport",
        "address": "78 Airport Blvd, #B2-208, Singapore 819666",
        "is_active": True,
    },
    {
        "store_code": "BREEZE-01",
        "name": "VictoriaEnso – Breeze by East (HQ & Warehouse)",
        "location": "Breeze by East",
        "address": "Singapore",
        "is_active": False,  # back-office only, not a retail floor
    },
    {
        "store_code": "ONLINE-01",
        "name": "VictoriaEnso – Online",
        "location": "Online",
        "address": "https://victoriaenso.com",
        "is_active": True,
    },
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def init_firebase() -> None:
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={"projectId": PROJECT_ID})


def ensure_store(db, payload: dict[str, Any]) -> tuple[str, str]:
    """Upsert by store_code. Returns (store_id, status) where status is
    'created' | 'updated' | 'unchanged'."""
    code = payload["store_code"]
    matches = list(
        db.collection("stores").where("store_code", "==", code).limit(1).stream()
    )
    now = datetime.now(timezone.utc)

    if matches:
        doc = matches[0]
        sid = doc.id
        existing = doc.to_dict() or {}
        # Compare the mutable fields. If anything has drifted, merge an update.
        drift = any(existing.get(k) != v for k, v in payload.items())
        if not drift:
            return sid, "unchanged"
        db.collection("stores").document(sid).set(
            {**payload, "updated_at": now}, merge=True
        )
        return sid, "updated"

    sid = str(uuid.uuid4())
    db.collection("stores").document(sid).set({
        "id": sid,
        "created_at": now,
        "updated_at": now,
        **payload,
    })
    return sid, "created"


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply", action="store_true", help="Actually provision. Default is dry-run."
    )
    args = parser.parse_args()

    if not args.apply:
        print("DRY RUN — no changes will be made. Re-run with --apply to provision.\n")

    # Print the plan
    print(f"{'store_code':12s}  {'active':6s}  name")
    print("-" * 80)
    for s in STORES:
        print(f"{s['store_code']:12s}  {str(s['is_active']):6s}  {s['name']}")
    print()

    if not args.apply:
        return

    init_firebase()
    db = firestore.client()

    for s in STORES:
        sid, status = ensure_store(db, s)
        print(f"  {s['store_code']:12s}  id={sid}  [{status}]")

    print("\n✓ Done. Run `python tools/scripts/seed_users.py --apply` next to grant roles.")


if __name__ == "__main__":
    main()
