#!/usr/bin/env python3
"""
Ensure the 5 canonical Victoria Enso stores exist in Firestore.

Idempotent: for each canonical ``store_code`` that has no existing Firestore
document, creates one with the structured profile. Existing docs are left
untouched (even duplicates) to avoid destructive cleanup by accident.

Prints a summary so you can see what shape the collection is in.

Usage:
  python ensure_stores.py            # dry-run
  python ensure_stores.py --apply
"""
from __future__ import annotations

import argparse
import os
import uuid
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import firestore


PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "victoriaensoapp")

CANONICAL_STORES = [
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
        "is_active": False,  # back-office only
    },
    {
        "store_code": "ONLINE-01",
        "name": "VictoriaEnso – Online",
        "location": "Online",
        "address": "https://victoriaenso.com",
        "is_active": True,
    },
]


def init() -> None:
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={"projectId": PROJECT_ID})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Actually create missing stores. Default is dry-run.")
    args = parser.parse_args()

    init()
    db = firestore.client()

    # Index existing docs by store_code
    existing_by_code: dict[str, list[str]] = {}
    for doc in db.collection("stores").stream():
        d = doc.to_dict() or {}
        code = d.get("store_code", "<none>")
        existing_by_code.setdefault(code, []).append(doc.id)

    print("Current state of Firestore stores collection:")
    for code in sorted(existing_by_code):
        ids = existing_by_code[code]
        flag = ""
        if code == "<none>":
            flag = "   (blank — candidates for cleanup)"
        elif code.startswith("STORE-"):
            flag = "   (legacy stub — candidate for cleanup)"
        print(f"  {code:30s}  {len(ids):4d} docs{flag}")

    print()
    plan: list[dict] = []
    for target in CANONICAL_STORES:
        code = target["store_code"]
        if code in existing_by_code and existing_by_code[code]:
            print(f"  [skip] {code:12s} — {len(existing_by_code[code])} doc(s) already present")
        else:
            print(f"  [NEW ] {code:12s} — will create: {target['name']}")
            plan.append(target)

    if not plan:
        print("\nNothing to create.")
        return

    if not args.apply:
        print(f"\n(dry run — would create {len(plan)} store doc(s). Re-run with --apply to persist.)")
        return

    now = datetime.now(timezone.utc)
    for target in plan:
        sid = str(uuid.uuid4())
        db.collection("stores").document(sid).set({
            "id": sid,
            "created_at": now,
            "updated_at": now,
            **target,
        })
        print(f"  created  {target['store_code']:12s}  id={sid}")

    print(f"\n{len(plan)} store(s) created.")


if __name__ == "__main__":
    main()
