#!/usr/bin/env python3
"""
Purge legacy ``STORE-*`` stub store documents from Firestore.

Earlier in the project's life, an unspecified number of placeholder
store docs with codes like ``STORE-01`` / ``STORE-FOO`` were inserted
to make multi-store flows compile. Now that the canonical store list
(JEWEL-01, TAKA-01, ISETAN-01, BREEZE-01, ONLINE-01) is the source of
truth, these stub documents are noise and need to go.

Default mode is dry-run. Use ``--apply`` to actually delete.

The script also flags (but does NOT delete) any store doc whose
``store_code`` is blank or matches none of the canonical codes — those
need a manual decision before purging because they may carry real data.

Usage:
  python tools/scripts/purge_legacy_stores.py            # dry-run audit
  python tools/scripts/purge_legacy_stores.py --apply    # actually delete STORE-*
"""
from __future__ import annotations

import argparse
import os

import firebase_admin
from firebase_admin import firestore


PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "victoriaensoapp")

CANONICAL_CODES = {"TAKA-01", "ISETAN-01", "JEWEL-01", "BREEZE-01", "ONLINE-01"}


def init() -> None:
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={"projectId": PROJECT_ID})


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete STORE-* documents (default: dry-run).",
    )
    parser.add_argument(
        "--include-blank",
        action="store_true",
        help="Also delete documents whose store_code is blank/missing. NOT recommended without manual review.",
    )
    args = parser.parse_args()

    init()
    db = firestore.client()

    legacy: list[tuple[str, str]] = []   # (doc_id, store_code)
    blank: list[str] = []                # doc_id with no store_code
    other: list[tuple[str, str]] = []    # other non-canonical codes (kept by default)

    for doc in db.collection("stores").stream():
        d = doc.to_dict() or {}
        code = (d.get("store_code") or "").strip()
        if not code:
            blank.append(doc.id)
        elif code.startswith("STORE-"):
            legacy.append((doc.id, code))
        elif code not in CANONICAL_CODES:
            other.append((doc.id, code))

    print(f"Canonical codes: {sorted(CANONICAL_CODES)}")
    print()
    print(f"Legacy STORE-* docs (will be purged):  {len(legacy)}")
    for doc_id, code in legacy:
        print(f"  - {code:20s}  doc_id={doc_id}")
    print()
    print(f"Blank-code docs (review manually):     {len(blank)}")
    for doc_id in blank:
        print(f"  - <no store_code>     doc_id={doc_id}")
    print()
    print(f"Other non-canonical codes (kept):      {len(other)}")
    for doc_id, code in other:
        print(f"  - {code:20s}  doc_id={doc_id}")
    print()

    targets = list(legacy)
    if args.include_blank:
        targets += [(doc_id, "<blank>") for doc_id in blank]

    if not targets:
        print("Nothing to purge.")
        return

    if not args.apply:
        print(f"(dry-run — would delete {len(targets)} doc(s). Re-run with --apply.)")
        return

    deleted = 0
    for doc_id, _code in targets:
        db.collection("stores").document(doc_id).delete()
        deleted += 1
    print(f"Deleted {deleted} legacy store doc(s) from Firestore.")


if __name__ == "__main__":
    main()
