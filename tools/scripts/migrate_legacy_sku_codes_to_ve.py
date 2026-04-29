#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

DEFAULT_PG_URL = "postgresql://retailsg:RetailSG2026Secure@127.0.0.1:5434/retailsg"


@dataclass(frozen=True)
class MigrationRow:
    sku_id: str
    store_id: str
    old_sku_code: str
    new_sku_code: str
    legacy_code: str | None
    description: str
    form_factor: str | None
    plu_code: str


FETCH_SQL = """
SELECT
    s.id::text AS sku_id,
    s.store_id::text AS store_id,
    s.sku_code AS old_sku_code,
    s.attributes->>'ve_padded_code' AS new_sku_code,
    s.legacy_code,
    s.description,
    s.form_factor,
    p.plu_code
FROM skus s
JOIN plus p ON p.sku_id = s.id
WHERE (s.sku_code LIKE 'GEN-%' OR s.sku_code NOT LIKE 'VE%')
  AND (s.attributes->>'ve_padded_code') IS NOT NULL
ORDER BY s.sku_code
"""


def _to_mapping(row: asyncpg.Record) -> MigrationRow:
    return MigrationRow(**dict(row))


async def load_candidates(conn: asyncpg.Connection) -> list[MigrationRow]:
    rows = await conn.fetch(FETCH_SQL)
    candidates = [_to_mapping(row) for row in rows]

    targets = [row.new_sku_code for row in candidates]
    if len(targets) != len(set(targets)):
        dupes = [code for code, count in Counter(targets).items() if count > 1]
        raise RuntimeError(f"Duplicate ve_padded_code targets found: {dupes[:20]}")

    old_codes = {row.old_sku_code for row in candidates}
    target_conflicts = await conn.fetch(
        """
        SELECT sku_code
        FROM skus
        WHERE sku_code = ANY($1::text[])
        """,
        targets,
    )
    conflicting = sorted(
        {
            row["sku_code"]
            for row in target_conflicts
            if row["sku_code"] not in old_codes
        }
    )
    if conflicting:
        raise RuntimeError(f"Target sku_code already exists outside migration set: {conflicting[:20]}")

    return candidates


def summarize(candidates: list[MigrationRow]) -> dict[str, Any]:
    return {
        "count": len(candidates),
        "by_type": dict(Counter(row.form_factor or "UNKNOWN" for row in candidates).most_common(20)),
        "sample": [
            {
                "sku_id": row.sku_id,
                "old_sku_code": row.old_sku_code,
                "new_sku_code": row.new_sku_code,
                "legacy_code": row.legacy_code,
                "plu_code": row.plu_code,
                "description": row.description,
            }
            for row in candidates[:20]
        ],
    }


async def update_postgres(conn: asyncpg.Connection, candidates: list[MigrationRow]) -> int:
    for row in candidates:
        await conn.execute(
            "UPDATE skus SET sku_code = $1, updated_at = NOW() WHERE id = $2::uuid",
            row.new_sku_code,
            row.sku_id,
        )
    return len(candidates)


def update_firestore(candidates: list[MigrationRow], *, apply: bool) -> dict[str, int]:
    updates = {
        "top_level_skus_updated": 0,
        "store_inventory_updated": 0,
        "top_level_skus_missing": 0,
        "store_inventory_missing": 0,
    }
    if not apply:
        return updates

    from app.firestore import db as firestore_db  # noqa: E402

    batch = firestore_db.batch()
    ops = 0

    def commit_if_needed() -> None:
        nonlocal batch, ops
        if ops and ops % 400 == 0:
            batch.commit()
            batch = firestore_db.batch()

    for row in candidates:
        top_ref = firestore_db.collection("skus").document(row.sku_id)
        top_snap = top_ref.get()
        if top_snap.exists:
            batch.update(top_ref, {"sku_code": row.new_sku_code})
            updates["top_level_skus_updated"] += 1
            ops += 1
            commit_if_needed()
        else:
            updates["top_level_skus_missing"] += 1

        inv_ref = firestore_db.collection(f"stores/{row.store_id}/inventory").document(row.sku_id)
        inv_snap = inv_ref.get()
        if inv_snap.exists:
            batch.update(inv_ref, {"sku_code": row.new_sku_code})
            updates["store_inventory_updated"] += 1
            ops += 1
            commit_if_needed()
        else:
            updates["store_inventory_missing"] += 1

    if ops % 400 != 0 and ops > 0:
        batch.commit()

    return updates


async def verify_postgres(conn: asyncpg.Connection) -> dict[str, int]:
    remaining = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM skus s
        JOIN plus p ON p.sku_id = s.id
        WHERE (s.sku_code LIKE 'GEN-%' OR s.sku_code NOT LIKE 'VE%')
          AND (s.attributes->>'ve_padded_code') IS NOT NULL
        """
    )
    return {"remaining_migratable_legacy_skus": int(remaining or 0)}


def verify_firestore(candidates: list[MigrationRow]) -> dict[str, int]:
    from app.firestore import db as firestore_db  # noqa: E402

    legacy_top = 0
    legacy_inventory = 0
    checked = 0
    for row in candidates:
        checked += 1
        top_snap = firestore_db.collection("skus").document(row.sku_id).get()
        if top_snap.exists and (top_snap.to_dict() or {}).get("sku_code") == row.old_sku_code:
            legacy_top += 1
        inv_snap = firestore_db.collection(f"stores/{row.store_id}/inventory").document(row.sku_id).get()
        if inv_snap.exists and (inv_snap.to_dict() or {}).get("sku_code") == row.old_sku_code:
            legacy_inventory += 1
    return {
        "checked_rows": checked,
        "firestore_top_level_still_legacy": legacy_top,
        "firestore_inventory_still_legacy": legacy_inventory,
    }


async def run(pg_url: str, *, apply: bool) -> None:
    conn = await asyncpg.connect(pg_url)
    try:
        candidates = await load_candidates(conn)
        summary = summarize(candidates)
        print(json.dumps(summary, indent=2, ensure_ascii=False))

        if not apply:
            print("\n(dry run — no Postgres or Firestore documents updated. Re-run with --apply to persist.)")
            return

        async with conn.transaction():
            updated_pg = await update_postgres(conn, candidates)

        fs_updates = update_firestore(candidates, apply=True)
        pg_verify = await verify_postgres(conn)
        fs_verify = verify_firestore(candidates)

        print("\nMigration complete.")
        print(
            json.dumps(
                {
                    "postgres_updated": updated_pg,
                    "firestore": fs_updates,
                    "postgres_verify": pg_verify,
                    "firestore_verify": fs_verify,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Rename live legacy sku_code rows to their ve_padded_code equivalents")
    parser.add_argument("--pg-url", default=DEFAULT_PG_URL)
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry-run)")
    args = parser.parse_args()
    asyncio.run(run(args.pg_url, apply=args.apply))


if __name__ == "__main__":
    main()
