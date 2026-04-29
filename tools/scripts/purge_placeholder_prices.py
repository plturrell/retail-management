#!/usr/bin/env python3
"""
Purge previously-synced placeholder price docs from Firestore.

Earlier versions of `sync_master_to_firestore.py` wrote synthetic prices
(``cost x 3``) tagged ``source: "master_sync_placeholder"`` so the POS
scan flow could be exercised before real retail prices were known. We've
since removed that behaviour — this script removes any leftover docs so
the live pricing surface only contains confirmed retail prices.

Default mode is dry-run. Use ``--apply`` to actually delete.

Usage:
  python tools/scripts/purge_placeholder_prices.py            # dry run
  python tools/scripts/purge_placeholder_prices.py --apply    # actually delete
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.firestore_helpers import (  # noqa: E402
    delete_document,
    query_collection,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete the placeholder price docs (default: dry-run).",
    )
    args = parser.parse_args()

    matches = query_collection(
        "prices",
        filters=[("source", "==", "master_sync_placeholder")],
    )
    print(f"Found {len(matches)} placeholder price doc(s) in Firestore.")

    if not matches:
        print("Nothing to purge.")
        return

    for m in matches[:20]:
        print(
            f"  - id={m.get('id')}  sku_id={m.get('sku_id')}  "
            f"store_id={m.get('store_id')}  price_incl_tax={m.get('price_incl_tax')}"
        )
    if len(matches) > 20:
        print(f"  … and {len(matches) - 20} more.")

    if not args.apply:
        print("\n(dry-run — re-run with --apply to delete.)")
        return

    deleted = 0
    for m in matches:
        doc_id = str(m.get("id"))
        if not doc_id:
            continue
        delete_document("prices", doc_id)
        deleted += 1
    print(f"\nDeleted {deleted} placeholder price doc(s) from Firestore.")


if __name__ == "__main__":
    main()
