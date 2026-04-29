#!/usr/bin/env python3
"""One-time live remap: `workshop` -> `warehouse`.

Touches the two live systems that still held historical values when this
script was added:

1. Postgres `skus.primary_stocking_location`
2. Firestore `stores/{store_id}/inventory/*`

Dry-run is the default. Pass `--apply` to perform updates.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.firestore import db as firestore_db  # noqa: E402


DEFAULT_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://retailsg:RetailSG2026Secure@127.0.0.1:5434/retailsg",
)

OLD_LOCATION = "workshop"
NEW_LOCATION = "warehouse"
FIRESTORE_BATCH_LIMIT = 400


@dataclass(frozen=True)
class FirestoreMatch:
    store_id: str
    store_code: str
    doc_id: str
    sku_code: str | None
    description: str | None
    has_legacy_field: bool


async def fetch_pg_matches(conn: AsyncConnection) -> list[dict[str, Any]]:
    rows = await conn.execute(
        text(
            """
            select
                s.id,
                s.sku_code,
                s.description,
                st.id as store_id,
                st.store_code
            from skus s
            left join stores st on st.id = s.store_id
            where s.primary_stocking_location = :old_location
            order by st.store_code nulls last, s.sku_code
            """
        ),
        {"old_location": OLD_LOCATION},
    )
    return [dict(row._mapping) for row in rows]


async def apply_pg_remap(conn: AsyncConnection) -> int:
    result = await conn.execute(
        text(
            """
            update skus
            set
                primary_stocking_location = :new_location,
                updated_at = now()
            where primary_stocking_location = :old_location
            """
        ),
        {"old_location": OLD_LOCATION, "new_location": NEW_LOCATION},
    )
    await conn.commit()
    return result.rowcount or 0


def fetch_firestore_matches() -> list[FirestoreMatch]:
    store_code_by_id: dict[str, str] = {}
    for store_snap in firestore_db.collection("stores").stream():
        store = store_snap.to_dict() or {}
        store_code_by_id[store_snap.id] = store.get("store_code") or store.get("name") or store_snap.id

    matches: list[FirestoreMatch] = []
    for store_id, store_code in store_code_by_id.items():
        query = firestore_db.collection(f"stores/{store_id}/inventory").where(
            "primary_stocking_location", "==", OLD_LOCATION
        )
        for snap in query.stream():
            data = snap.to_dict() or {}
            matches.append(
                FirestoreMatch(
                    store_id=store_id,
                    store_code=store_code,
                    doc_id=snap.id,
                    sku_code=data.get("sku_code"),
                    description=data.get("description"),
                    has_legacy_field="stocking_location" in data,
                )
            )
    return matches


def apply_firestore_remap(matches: list[FirestoreMatch]) -> int:
    if not matches:
        return 0

    now = datetime.now(timezone.utc)
    updated = 0
    batch = firestore_db.batch()
    pending = 0

    for match in matches:
        ref = firestore_db.collection(f"stores/{match.store_id}/inventory").document(match.doc_id)
        payload: dict[str, Any] = {
            "primary_stocking_location": NEW_LOCATION,
            "updated_at": now,
        }
        if match.has_legacy_field:
            payload["stocking_location"] = NEW_LOCATION
        batch.update(ref, payload)
        pending += 1
        updated += 1

        if pending >= FIRESTORE_BATCH_LIMIT:
            batch.commit()
            batch = firestore_db.batch()
            pending = 0

    if pending:
        batch.commit()

    return updated


def print_summary(*, pg_matches: list[dict[str, Any]], firestore_matches: list[FirestoreMatch]) -> None:
    print("\nCurrent workshop footprint")
    print("-------------------------")
    print(f"Postgres rows : {len(pg_matches)}")
    print(f"Firestore docs: {len(firestore_matches)}")

    pg_by_store = Counter(row.get("store_code") or "unknown" for row in pg_matches)
    fs_by_store = Counter(match.store_code for match in firestore_matches)
    print(f"PG by store   : {dict(pg_by_store)}")
    print(f"FS by store   : {dict(fs_by_store)}")

    if pg_matches:
        print("\nPostgres sample:")
        for row in pg_matches[:10]:
            print(f"  {row.get('store_code')}: {row.get('sku_code')}  {row.get('description')}")

    if firestore_matches:
        print("\nFirestore sample:")
        for match in firestore_matches[:10]:
            print(f"  {match.store_code}: {match.sku_code}  {match.description}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", default=DEFAULT_DATABASE_URL, help="Async SQLAlchemy database URL")
    parser.add_argument("--apply", action="store_true", help="Perform the live remap")
    args = parser.parse_args()

    engine = create_async_engine(args.db_url)
    try:
        async with engine.connect() as conn:
            pg_matches_before = await fetch_pg_matches(conn)
            firestore_matches_before = fetch_firestore_matches()
            print_summary(pg_matches=pg_matches_before, firestore_matches=firestore_matches_before)

            if not args.apply:
                print("\nDry run only. Re-run with --apply to update both systems.")
                return

            print("\nApplying remap...")
            pg_updated = await apply_pg_remap(conn)
            firestore_updated = apply_firestore_remap(firestore_matches_before)

            pg_matches_after = await fetch_pg_matches(conn)
            firestore_matches_after = fetch_firestore_matches()

            print("\nApply results")
            print("-------------")
            print(f"Postgres updated : {pg_updated}")
            print(f"Firestore updated: {firestore_updated}")
            print(f"Postgres remaining : {len(pg_matches_after)}")
            print(f"Firestore remaining: {len(firestore_matches_after)}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
