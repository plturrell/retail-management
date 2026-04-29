#!/usr/bin/env python3
"""One-shot backfill: Cloud SQL Postgres → Firestore.

Moves operational data (brands, categories, stores, skus, prices, plus,
inventories) from the Postgres source-of-truth into the Firestore layout
that the live API routers already expect. Also:

  * Creates ISETAN-01 (Isetan Scotts counter) and ONLINE-01 (e-commerce)
    in Postgres if missing.
  * Wipes the 4 orphan Firestore `stores/*` docs (their UUIDs don't match
    Postgres). Re-creates them with Postgres UUIDs + ``store_code``.
  * Preserves the 3 existing Firestore users untouched (they're real).
  * Re-links each user role from the old Firestore store UUID to the new
    Postgres-matched UUID (by store name).

Firestore layout after backfill::

    brands/{brand_id}
    categories/{category_id}
    plus/{plu_id}
    stores/{store_id}                    (with store_code)
    stores/{store_id}/roles/{role_id}
    stores/{store_id}/inventory/{sku_id} (SKU master, brand_name denormalized)
    stores/{store_id}/prices/{price_id}
    stores/{store_id}/stock/{inventory_id}

Usage::

    # Dry run — show counts only, no writes
    python tools/scripts/backfill_pg_to_firestore.py --dry-run

    # Real run
    python tools/scripts/backfill_pg_to_firestore.py

Requires ``cloud-sql-proxy`` listening on 127.0.0.1:5433.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg


REPO_ROOT = Path(__file__).resolve().parents[2]

# Make `app.firestore` importable
sys.path.insert(0, str(REPO_ROOT / "backend"))

DEFAULT_PG_URL = "postgresql://retailsg:RetailSG2026Secure@127.0.0.1:5433/retailsg"

ISETAN_DEFAULTS = {
    "store_code": "ISETAN-01",
    "name": "Isetan Scotts",
    "location": "Isetan Scotts, Level 2",
    "address": "350 Orchard Road, Shaw House, Singapore 238868",
    "city": "Singapore",
    "country": "Singapore",
    "postal_code": "238868",
    "currency": "SGD",
    "is_active": True,
    "store_type": "outlet",
    "business_hours_start": time(10, 0),
    "business_hours_end": time(21, 30),
}

ONLINE_DEFAULTS = {
    "store_code": "ONLINE-01",
    "name": "Victoria Enso Online",
    "location": "E-commerce",
    "address": "Online — fulfilment from BREEZE-01",
    "city": "Singapore",
    "country": "Singapore",
    "postal_code": "088539",
    "currency": "SGD",
    "is_active": True,
    "store_type": "online",
    "business_hours_start": time(0, 0),
    "business_hours_end": time(23, 59),
}


# ── Conversion helpers ────────────────────────────────────────────────────────

def _to_firestore(value: Any) -> Any:
    """Convert asyncpg-native values into Firestore-safe JSON-ish values."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return value


def _row_to_doc(row: asyncpg.Record, *, parse_json_fields: tuple[str, ...] = ()) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in dict(row).items():
        if key in parse_json_fields and isinstance(value, str):
            try:
                out[key] = json.loads(value)
            except (TypeError, ValueError):
                out[key] = value
        else:
            out[key] = _to_firestore(value)
    return out


# ── Postgres side: ensure expected store rows exist ───────────────────────────

async def ensure_store(conn: asyncpg.Connection, defaults: dict[str, Any], *, dry_run: bool) -> str:
    """Return the Postgres UUID for ``defaults['store_code']``, creating it if missing."""
    code = defaults["store_code"]
    row = await conn.fetchrow("SELECT id FROM stores WHERE store_code = $1", code)
    if row:
        print(f"  {code} already in Postgres: {row['id']}")
        return str(row["id"])

    if dry_run:
        print(f"  [dry-run] would INSERT {code} into Postgres")
        return "pending-uuid"

    new_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO stores (
            id, store_code, name, location, address,
            city, country, postal_code, currency,
            is_active, store_type,
            business_hours_start, business_hours_end,
            created_at, updated_at
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$14)
        """,
        new_id,
        defaults["store_code"],
        defaults["name"],
        defaults["location"],
        defaults["address"],
        defaults["city"],
        defaults["country"],
        defaults["postal_code"],
        defaults["currency"],
        defaults["is_active"],
        defaults["store_type"],
        defaults["business_hours_start"],
        defaults["business_hours_end"],
        datetime.now(timezone.utc).replace(tzinfo=None),
    )
    print(f"  Inserted {code} → {new_id}")
    return str(new_id)


# ── Firestore side ────────────────────────────────────────────────────────────

def load_firestore_client():
    from app.firestore import db  # noqa: E402
    return db


def capture_existing_role_map(fs_db) -> list[dict[str, Any]]:
    """Snapshot the test-manager's role assignments across the old FS stores.

    Returns list of dicts: ``{"store_name": <str>, "role_doc": <dict>}``.
    After we rebuild stores with Postgres UUIDs, we re-insert a role doc
    under the new store (matched by name) for each captured entry.
    """
    captured: list[dict[str, Any]] = []
    for store_snap in fs_db.collection("stores").stream():
        store_data = store_snap.to_dict() or {}
        name = store_data.get("name", "")
        for role_snap in store_snap.reference.collection("roles").stream():
            role = role_snap.to_dict() or {}
            captured.append({"store_name": name, "role_doc": role})
    return captured


def _fs_name_to_pg_code(fs_name: str) -> str | None:
    """Map a Firestore store name → Postgres store_code.

    Only the 4 canonical VictoriaEnso store names match. Test/dev junk
    (``Test Store``, ``JEWEL-B1-241`` etc.) returns None and is dropped.
    """
    if not fs_name.lower().startswith("victoriaenso"):
        return None
    n = fs_name.lower()
    if "taka" in n:
        return "TAKA-01"
    if "jewel" in n:
        return "JEWEL-01"
    if "breeze" in n:
        return "BREEZE-01"
    if "isetan" in n:
        return "ISETAN-01"
    if "online" in n:
        return "ONLINE-01"
    return None


def wipe_stores_collection(fs_db, *, dry_run: bool) -> int:
    """Delete every doc under ``stores`` and all its known subcollections."""
    deleted = 0
    for store_snap in fs_db.collection("stores").stream():
        # Known subcollections to purge. We enumerate explicitly so we don't
        # accidentally leave data hanging under an unfamiliar subpath.
        for sub in store_snap.reference.collections():
            for child in sub.stream():
                if not dry_run:
                    child.reference.delete()
                deleted += 1
        if not dry_run:
            store_snap.reference.delete()
        deleted += 1
    return deleted


def wipe_top_level_collection(fs_db, collection: str, *, dry_run: bool) -> int:
    deleted = 0
    for snap in fs_db.collection(collection).stream():
        if not dry_run:
            snap.reference.delete()
        deleted += 1
    return deleted


def batched_write(fs_db, collection_path: str, docs: list[tuple[str, dict[str, Any]]], *, dry_run: bool) -> int:
    """Write ``docs`` (list of (doc_id, data)) to ``collection_path`` in batches."""
    if dry_run:
        return len(docs)
    batch = fs_db.batch()
    count = 0
    for doc_id, data in docs:
        ref = fs_db.collection(collection_path).document(doc_id)
        batch.set(ref, data)
        count += 1
        if count % 400 == 0:
            batch.commit()
            batch = fs_db.batch()
    if count % 400 != 0:
        batch.commit()
    return count


# ── Migration steps ───────────────────────────────────────────────────────────

async def migrate(pg_url: str, *, dry_run: bool) -> None:
    fs_db = load_firestore_client()
    conn = await asyncpg.connect(pg_url)
    try:
        # 1) Ensure ISETAN-01 + ONLINE-01 exist in PG.
        print("\n[1/8] Ensure ISETAN-01 + ONLINE-01 in Postgres")
        await ensure_store(conn, ISETAN_DEFAULTS, dry_run=dry_run)
        await ensure_store(conn, ONLINE_DEFAULTS, dry_run=dry_run)

        # 2) Snapshot FS roles before we wipe.
        print("\n[2/8] Snapshot existing Firestore role assignments")
        captured_roles = capture_existing_role_map(fs_db)
        print(f"  captured {len(captured_roles)} role docs across old FS stores")

        # 3) Wipe FS stores + top-level brands/categories/plus.
        print("\n[3/8] Wipe Firestore stores + top-level catalogue collections")
        n = wipe_stores_collection(fs_db, dry_run=dry_run)
        print(f"  {'(dry-run) ' if dry_run else ''}deleted {n} docs from stores/*")
        for col in ("brands", "categories", "plus"):
            n = wipe_top_level_collection(fs_db, col, dry_run=dry_run)
            print(f"  {'(dry-run) ' if dry_run else ''}deleted {n} docs from {col}")

        # 4) Rebuild stores from PG.
        # Dedup by store_code: if a Firestore doc with this code already
        # exists at a *different* UUID, reuse that UUID so we don't strand
        # roles/inventory under the orphan doc. (Step 3's wipe should have
        # cleared these, but be defensive — a partial run that skipped the
        # wipe would otherwise leave duplicates.)
        print("\n[4/8] Rebuild stores from Postgres")
        store_rows = await conn.fetch("SELECT * FROM stores ORDER BY store_code")
        existing_by_code: dict[str, str] = {}
        for snap in fs_db.collection("stores").stream():
            sd = snap.to_dict() or {}
            sc = sd.get("store_code")
            if sc:
                if sc in existing_by_code:
                    raise RuntimeError(
                        f"Refusing to proceed: Firestore already has duplicate "
                        f"store_code={sc!r} at {existing_by_code[sc]} and {snap.id}. "
                        f"Consolidate manually before re-running the backfill."
                    )
                existing_by_code[sc] = snap.id
        store_docs: list[tuple[str, dict[str, Any]]] = []
        # store_id_by_pg: PG UUID -> the Firestore doc ID we actually wrote to.
        # When we reused an existing FS UUID, this differs from the PG UUID,
        # and downstream steps must use the FS-side ID for all path writes.
        store_id_by_pg: dict[str, str] = {}
        for r in store_rows:
            target_id = existing_by_code.get(r["store_code"], str(r["id"]))
            store_docs.append((target_id, _row_to_doc(r)))
            store_id_by_pg[str(r["id"])] = target_id
        written = batched_write(fs_db, "stores", store_docs, dry_run=dry_run)
        print(f"  wrote {written} store docs (reused {sum(1 for r in store_rows if r['store_code'] in existing_by_code)} existing FS UUIDs)")

        # 5) Re-link captured roles under the new store IDs.
        print("\n[5/8] Re-link role assignments")
        pg_store_by_code = {r["store_code"]: store_id_by_pg[str(r["id"])] for r in store_rows}
        relinked = 0
        for entry in captured_roles:
            code = _fs_name_to_pg_code(entry["store_name"])
            if not code:
                print(f"  skipped role for unrecognized store name: {entry['store_name']}")
                continue
            new_store_id = pg_store_by_code.get(code)
            if not new_store_id:
                print(f"  no PG store for code {code}; skipping")
                continue
            role = dict(entry["role_doc"])
            role["store_id"] = new_store_id
            if not role.get("id"):
                role["id"] = str(uuid.uuid4())
            if not dry_run:
                fs_db.collection(f"stores/{new_store_id}/roles").document(role["id"]).set(role)
            relinked += 1
        print(f"  re-linked {relinked} role docs")

        # 6) Brands + categories (top-level).
        print("\n[6/8] Brands + categories")
        brand_rows = await conn.fetch("SELECT * FROM brands ORDER BY name")
        brand_docs = [(str(r["id"]), _row_to_doc(r)) for r in brand_rows]
        print(f"  brands: {batched_write(fs_db, 'brands', brand_docs, dry_run=dry_run)}")
        brand_name_by_id = {str(r["id"]): r["name"] for r in brand_rows}

        cat_rows = await conn.fetch("SELECT * FROM categories")
        cat_docs = [(str(r["id"]), _row_to_doc(r)) for r in cat_rows]
        print(f"  categories: {batched_write(fs_db, 'categories', cat_docs, dry_run=dry_run)}")

        # 7) Per-store: SKUs (inventory), prices, stock (inventories).
        print("\n[7/8] Per-store catalogue")
        sku_rows = await conn.fetch("SELECT * FROM skus")
        price_rows = await conn.fetch("SELECT * FROM prices")
        inv_rows = await conn.fetch("SELECT * FROM inventories")

        # Group by Firestore store_id (after PG→FS UUID remap from step 4).
        def _fs_sid(pg_sid: str | None) -> str | None:
            return store_id_by_pg.get(pg_sid) if pg_sid else None

        by_store_skus: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for r in sku_rows:
            sid = _fs_sid(str(r["store_id"]) if r["store_id"] else None)
            if sid is None:
                continue
            doc = _row_to_doc(r, parse_json_fields=("attributes",))
            doc["brand_name"] = brand_name_by_id.get(str(r["brand_id"]))
            by_store_skus.setdefault(sid, []).append((str(r["id"]), doc))

        by_store_prices: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for r in price_rows:
            # A price row MAY have store_id=NULL in PG. Default to JEWEL-01
            # because that's where all SKUs live today.
            sid = _fs_sid(str(r["store_id"])) if r["store_id"] else pg_store_by_code.get("JEWEL-01")
            if sid is None:
                continue
            doc = _row_to_doc(r)
            by_store_prices.setdefault(sid, []).append((str(r["id"]), doc))

        by_store_stock: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for r in inv_rows:
            sid = _fs_sid(str(r["store_id"]) if r["store_id"] else None)
            if sid is None:
                continue
            doc = _row_to_doc(r)
            by_store_stock.setdefault(sid, []).append((str(r["id"]), doc))

        for r in store_rows:
            store_id = store_id_by_pg[str(r["id"])]
            skus = by_store_skus.get(store_id, [])
            prices = by_store_prices.get(store_id, [])
            stock = by_store_stock.get(store_id, [])
            sc = r["store_code"]
            written_skus = batched_write(fs_db, f"stores/{store_id}/inventory", skus, dry_run=dry_run)
            written_prices = batched_write(fs_db, f"stores/{store_id}/prices", prices, dry_run=dry_run)
            written_stock = batched_write(fs_db, f"stores/{store_id}/stock", stock, dry_run=dry_run)
            print(f"  {sc}: {written_skus} skus, {written_prices} prices, {written_stock} stock positions")

        # 8) PLUs (top-level).
        print("\n[8/8] PLUs (top-level)")
        plu_rows = await conn.fetch("SELECT * FROM plus")
        plu_docs = [(str(r["id"]), _row_to_doc(r)) for r in plu_rows]
        print(f"  plus: {batched_write(fs_db, 'plus', plu_docs, dry_run=dry_run)}")

    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-url", default=DEFAULT_PG_URL)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"Backfill Postgres → Firestore ({'DRY RUN' if args.dry_run else 'LIVE'})")
    print(f"PG URL: {args.pg_url.split('@', 1)[-1]}")
    asyncio.run(migrate(args.pg_url, dry_run=args.dry_run))
    print("\nDone.")


if __name__ == "__main__":
    main()
