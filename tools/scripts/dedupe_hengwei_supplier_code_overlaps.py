#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

DEFAULT_PG_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://retailsg:RetailSG2026Secure@127.0.0.1:5434/retailsg",
)
DEFAULT_EXPORT_DIR = REPO_ROOT / "data" / "exports"

_GENERIC_DESCRIPTIONS = {
    "",
    "decoration",
    "decorations",
    "decor",
    "storage",
    "component",
    "piece",
    "bookend",
    "bookends",
    "hang decorations",
}


@dataclass(frozen=True)
class LinkStats:
    inventory_qty: int
    inventory_rows: int
    prices: int
    promotions: int
    order_items: int
    purchase_order_items: int
    supplier_products: int
    plus_rows: int


@dataclass(frozen=True)
class SkuSnapshot:
    sku_id: str
    store_id: str
    store_code: str | None
    sku_code: str
    legacy_code: str | None
    supplier_code: str | None
    description: str
    long_description: str
    form_factor: str | None
    cost_price: float | None
    attributes: dict[str, Any]
    links: LinkStats


@dataclass(frozen=True)
class OverlapPair:
    supplier_code: str
    canonical: SkuSnapshot
    duplicate: SkuSnapshot
    preferred_identifier_sku_code: str
    preferred_identifier_plu_code: str | None
    merged_description: str
    merged_long_description: str
    merged_form_factor: str | None
    merged_attributes: dict[str, Any]


OVERLAP_SQL = """
WITH rebuilt AS (
    SELECT
        s.id::text AS rebuilt_id,
        s.store_id::text AS rebuilt_store_id,
        st.store_code AS rebuilt_store_code,
        s.sku_code AS rebuilt_sku_code,
        s.legacy_code AS rebuilt_legacy_code,
        s.attributes->>'supplier_sku_code' AS supplier_code,
        COALESCE(s.description, '') AS rebuilt_description,
        COALESCE(s.long_description, '') AS rebuilt_long_description,
        s.form_factor AS rebuilt_form_factor,
        s.cost_price::float8 AS rebuilt_cost_price,
        s.attributes AS rebuilt_attributes
    FROM skus s
    LEFT JOIN stores st ON st.id = s.store_id
    WHERE s.attributes ? 'previous_sku_code'
)
SELECT
    rebuilt_id,
    rebuilt_store_id,
    rebuilt_store_code,
    rebuilt_sku_code,
    rebuilt_legacy_code,
    supplier_code,
    rebuilt_description,
    rebuilt_long_description,
    rebuilt_form_factor,
    rebuilt_cost_price,
    rebuilt_attributes,
    v.id::text AS ve_id,
    v.store_id::text AS ve_store_id,
    vst.store_code AS ve_store_code,
    v.sku_code AS ve_sku_code,
    v.legacy_code AS ve_legacy_code,
    COALESCE(v.description, '') AS ve_description,
    COALESCE(v.long_description, '') AS ve_long_description,
    v.form_factor AS ve_form_factor,
    v.cost_price::float8 AS ve_cost_price,
    v.attributes AS ve_attributes
FROM rebuilt
JOIN skus v ON v.legacy_code = rebuilt.supplier_code
LEFT JOIN stores vst ON vst.id = v.store_id
WHERE rebuilt.supplier_code IS NOT NULL
  AND v.sku_code <> rebuilt.rebuilt_sku_code
ORDER BY rebuilt.supplier_code, rebuilt.rebuilt_sku_code
"""


def _normalize_db_url(value: str) -> str:
    return value.replace("postgresql+asyncpg://", "postgresql://", 1)


def _conn_kwargs(pg_url: str) -> dict[str, Any]:
    parsed = urlparse(_normalize_db_url(pg_url))
    return {
        "dbname": parsed.path.lstrip("/"),
        "user": parsed.username,
        "password": parsed.password,
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 5432,
        "sslmode": "disable",
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(str(value).split()).strip()


def _coerce_attributes(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def is_generic_description(value: str | None) -> bool:
    normalized = _normalize_text(value).lower()
    return normalized in _GENERIC_DESCRIPTIONS


def choose_best_description(*values: str | None) -> str:
    normalized = [_normalize_text(value) for value in values if _normalize_text(value)]
    specific = [value for value in normalized if not is_generic_description(value)]
    if specific:
        return max(specific, key=len)
    if normalized:
        return max(normalized, key=len)
    return ""


def choose_best_form_factor(*values: str | None) -> str | None:
    normalized = [_normalize_text(value) for value in values if _normalize_text(value)]
    if not normalized:
        return None
    specific = [value for value in normalized if value.lower() != "decorative object"]
    if specific:
        return max(specific, key=len)
    return normalized[0]


def choose_canonical_side(rebuilt: SkuSnapshot, ve: SkuSnapshot) -> str:
    # Keep the row that carries supplier/PO/sales history unless the VE row
    # clearly has the stronger operational footprint.
    if ve.links.order_items > rebuilt.links.order_items:
        return "ve"
    if rebuilt.links.order_items > ve.links.order_items:
        return "rebuilt"
    if ve.links.purchase_order_items > rebuilt.links.purchase_order_items:
        return "ve"
    if rebuilt.links.purchase_order_items > ve.links.purchase_order_items:
        return "rebuilt"
    if ve.links.supplier_products > rebuilt.links.supplier_products:
        return "ve"
    if rebuilt.links.supplier_products > ve.links.supplier_products:
        return "rebuilt"
    return "rebuilt"


def merge_attributes(
    canonical_attributes: dict[str, Any],
    duplicate_attributes: dict[str, Any],
    *,
    supplier_code: str,
    duplicate_sku_code: str,
    duplicate_sku_id: str,
    merged_form_factor: str | None,
    merged_description: str,
) -> dict[str, Any]:
    merged = dict(duplicate_attributes)
    merged.update(canonical_attributes)
    merged["supplier_sku_code"] = supplier_code
    merged["deduped_supplier_overlap"] = True
    merged["merged_duplicate_sku_code"] = duplicate_sku_code
    merged["merged_duplicate_sku_id"] = duplicate_sku_id
    merged["normalized_form_factor"] = merged_form_factor
    merged["normalized_description"] = merged_description
    return merged


def build_overlap_pair(
    rebuilt: SkuSnapshot,
    ve: SkuSnapshot,
    *,
    supplier_code: str,
    ve_plu_code: str | None,
) -> OverlapPair:
    canonical_side = choose_canonical_side(rebuilt, ve)
    canonical = rebuilt if canonical_side == "rebuilt" else ve
    duplicate = ve if canonical_side == "rebuilt" else rebuilt

    merged_description = choose_best_description(ve.description, rebuilt.description)
    merged_long_description = choose_best_description(
        ve.long_description,
        rebuilt.long_description,
        merged_description,
    )
    merged_form_factor = choose_best_form_factor(ve.form_factor, rebuilt.form_factor)
    merged_attributes = merge_attributes(
        canonical.attributes,
        duplicate.attributes,
        supplier_code=supplier_code,
        duplicate_sku_code=duplicate.sku_code,
        duplicate_sku_id=duplicate.sku_id,
        merged_form_factor=merged_form_factor,
        merged_description=merged_description,
    )
    return OverlapPair(
        supplier_code=supplier_code,
        canonical=canonical,
        duplicate=duplicate,
        preferred_identifier_sku_code=ve.sku_code,
        preferred_identifier_plu_code=ve_plu_code,
        merged_description=merged_description,
        merged_long_description=merged_long_description,
        merged_form_factor=merged_form_factor,
        merged_attributes=merged_attributes,
    )


def _fetch_link_stats(cur: psycopg2.extensions.cursor, sku_id: str) -> LinkStats:
    queries = {
        "inventory_qty": "SELECT COALESCE(SUM(qty_on_hand), 0) FROM inventories WHERE sku_id = %s::uuid",
        "inventory_rows": "SELECT COUNT(*) FROM inventories WHERE sku_id = %s::uuid",
        "prices": "SELECT COUNT(*) FROM prices WHERE sku_id = %s::uuid",
        "promotions": "SELECT COUNT(*) FROM promotions WHERE sku_id = %s::uuid",
        "order_items": "SELECT COUNT(*) FROM order_items WHERE sku_id = %s::uuid",
        "purchase_order_items": "SELECT COUNT(*) FROM purchase_order_items WHERE sku_id = %s::uuid",
        "supplier_products": "SELECT COUNT(*) FROM supplier_products WHERE sku_id = %s::uuid",
        "plus_rows": "SELECT COUNT(*) FROM plus WHERE sku_id = %s::uuid",
    }
    values: dict[str, int] = {}
    for key, sql in queries.items():
        cur.execute(sql, (sku_id,))
        values[key] = int(cur.fetchone()[0] or 0)
    return LinkStats(**values)


def _fetch_plu_code(cur: psycopg2.extensions.cursor, sku_id: str) -> str | None:
    cur.execute("SELECT plu_code FROM plus WHERE sku_id = %s::uuid ORDER BY created_at NULLS LAST, id LIMIT 1", (sku_id,))
    row = cur.fetchone()
    return str(row[0]) if row and row[0] else None


def _row_to_snapshot(row: dict[str, Any], *, prefix: str, links: LinkStats) -> SkuSnapshot:
    return SkuSnapshot(
        sku_id=str(row[f"{prefix}_id"]),
        store_id=str(row[f"{prefix}_store_id"]),
        store_code=row.get(f"{prefix}_store_code"),
        sku_code=row[f"{prefix}_sku_code"],
        legacy_code=row.get(f"{prefix}_legacy_code"),
        supplier_code=row.get("supplier_code"),
        description=row.get(f"{prefix}_description", ""),
        long_description=row.get(f"{prefix}_long_description", ""),
        form_factor=row.get(f"{prefix}_form_factor"),
        cost_price=float(row[f"{prefix}_cost_price"]) if row.get(f"{prefix}_cost_price") is not None else None,
        attributes=_coerce_attributes(row.get(f"{prefix}_attributes")),
        links=links,
    )


def load_overlap_pairs(conn: psycopg2.extensions.connection) -> list[OverlapPair]:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute(OVERLAP_SQL)
        rows = cur.fetchall()
        pairs: list[OverlapPair] = []
        for row in rows:
            rebuilt_links = _fetch_link_stats(cur, row["rebuilt_id"])
            ve_links = _fetch_link_stats(cur, row["ve_id"])
            rebuilt = _row_to_snapshot(row, prefix="rebuilt", links=rebuilt_links)
            ve = _row_to_snapshot(row, prefix="ve", links=ve_links)
            ve_plu_code = _fetch_plu_code(cur, ve.sku_id)
            pairs.append(build_overlap_pair(rebuilt, ve, supplier_code=row["supplier_code"], ve_plu_code=ve_plu_code))
        return pairs
    finally:
        cur.close()


def summarize(pairs: list[OverlapPair]) -> dict[str, Any]:
    return {
        "pair_count": len(pairs),
        "canonical_store_counts": {
            key: sum(1 for pair in pairs if (pair.canonical.store_code or "UNKNOWN") == key)
            for key in sorted({pair.canonical.store_code or "UNKNOWN" for pair in pairs})
        },
        "identifier_reused_count": sum(1 for pair in pairs if pair.preferred_identifier_sku_code == pair.duplicate.sku_code),
        "sample": [
            {
                "supplier_code": pair.supplier_code,
                "canonical_sku_id": pair.canonical.sku_id,
                "canonical_current_sku": pair.canonical.sku_code,
                "duplicate_sku_id": pair.duplicate.sku_id,
                "duplicate_sku": pair.duplicate.sku_code,
                "final_sku_code": pair.preferred_identifier_sku_code,
                "final_plu_code": pair.preferred_identifier_plu_code,
                "merged_description": pair.merged_description,
                "merged_form_factor": pair.merged_form_factor,
            }
            for pair in pairs[:20]
        ],
    }


def _merge_inventory_rows(cur: psycopg2.extensions.cursor, *, canonical_id: str, duplicate_id: str) -> None:
    cur.execute(
        """
        SELECT id::text, store_id::text, COALESCE(qty_on_hand, 0) AS qty_on_hand,
               COALESCE(reorder_level, 0) AS reorder_level, COALESCE(reorder_qty, 0) AS reorder_qty
        FROM inventories
        WHERE sku_id = %s::uuid
        ORDER BY id
        FOR UPDATE
        """,
        (duplicate_id,),
    )
    duplicate_rows = cur.fetchall()
    for row in duplicate_rows:
        cur.execute(
            """
            SELECT id::text, COALESCE(qty_on_hand, 0) AS qty_on_hand,
                   COALESCE(reorder_level, 0) AS reorder_level, COALESCE(reorder_qty, 0) AS reorder_qty
            FROM inventories
            WHERE sku_id = %s::uuid AND store_id = %s::uuid
            LIMIT 1
            FOR UPDATE
            """,
            (canonical_id, row["store_id"]),
        )
        existing = cur.fetchone()
        if existing:
            cur.execute(
                """
                UPDATE inventories
                SET qty_on_hand = COALESCE(qty_on_hand, 0) + %s,
                    reorder_level = GREATEST(COALESCE(reorder_level, 0), %s),
                    reorder_qty = GREATEST(COALESCE(reorder_qty, 0), %s),
                    updated_at = NOW(),
                    last_updated = NOW()
                WHERE id = %s::uuid
                """,
                (row["qty_on_hand"], row["reorder_level"], row["reorder_qty"], existing["id"]),
            )
            cur.execute("DELETE FROM inventories WHERE id = %s::uuid", (row["id"],))
        else:
            cur.execute(
                "UPDATE inventories SET sku_id = %s::uuid, updated_at = NOW(), last_updated = NOW() WHERE id = %s::uuid",
                (canonical_id, row["id"]),
            )


def _reassign_simple_children(cur: psycopg2.extensions.cursor, *, canonical_id: str, duplicate_id: str) -> None:
    for table in ("prices", "promotions", "order_items", "purchase_order_items"):
        cur.execute(f"UPDATE {table} SET sku_id = %s::uuid WHERE sku_id = %s::uuid", (canonical_id, duplicate_id))


def _merge_supplier_products(cur: psycopg2.extensions.cursor, *, canonical_id: str, duplicate_id: str) -> None:
    cur.execute(
        """
        SELECT id::text, supplier_id::text, supplier_sku_code
        FROM supplier_products
        WHERE sku_id = %s::uuid
        ORDER BY id
        FOR UPDATE
        """,
        (duplicate_id,),
    )
    rows = cur.fetchall()
    for row in rows:
        cur.execute(
            """
            SELECT id::text
            FROM supplier_products
            WHERE sku_id = %s::uuid
              AND supplier_id = %s::uuid
              AND COALESCE(supplier_sku_code, '') = COALESCE(%s, '')
            LIMIT 1
            FOR UPDATE
            """,
            (canonical_id, row["supplier_id"], row["supplier_sku_code"]),
        )
        existing = cur.fetchone()
        if existing:
            cur.execute("DELETE FROM supplier_products WHERE id = %s::uuid", (row["id"],))
        else:
            cur.execute("UPDATE supplier_products SET sku_id = %s::uuid, updated_at = NOW() WHERE id = %s::uuid", (canonical_id, row["id"]))


def _move_plus_rows(
    cur: psycopg2.extensions.cursor,
    *,
    canonical_id: str,
    duplicate_id: str,
    final_plu_code: str | None,
) -> None:
    cur.execute("SELECT id::text, plu_code FROM plus WHERE sku_id = %s::uuid ORDER BY id FOR UPDATE", (canonical_id,))
    canonical_plus = cur.fetchall()
    cur.execute("SELECT id::text, plu_code FROM plus WHERE sku_id = %s::uuid ORDER BY id FOR UPDATE", (duplicate_id,))
    duplicate_plus = cur.fetchall()

    desired_source = None
    if final_plu_code:
        for row in duplicate_plus + canonical_plus:
            if row["plu_code"] == final_plu_code:
                desired_source = row
                break

    for row in canonical_plus:
        if desired_source and row["id"] == desired_source["id"]:
            continue
        cur.execute("DELETE FROM plus WHERE id = %s::uuid", (row["id"],))

    if desired_source:
        cur.execute("UPDATE plus SET sku_id = %s::uuid WHERE id = %s::uuid", (canonical_id, desired_source["id"]))
        for row in duplicate_plus:
            if row["id"] != desired_source["id"]:
                cur.execute("DELETE FROM plus WHERE id = %s::uuid", (row["id"],))
    else:
        for row in duplicate_plus:
            cur.execute("UPDATE plus SET sku_id = %s::uuid WHERE id = %s::uuid", (canonical_id, row["id"]))


def _apply_pair_postgres(cur: psycopg2.extensions.cursor, pair: OverlapPair) -> None:
    canonical_id = pair.canonical.sku_id
    duplicate_id = pair.duplicate.sku_id

    _merge_inventory_rows(cur, canonical_id=canonical_id, duplicate_id=duplicate_id)
    _reassign_simple_children(cur, canonical_id=canonical_id, duplicate_id=duplicate_id)
    _merge_supplier_products(cur, canonical_id=canonical_id, duplicate_id=duplicate_id)
    _move_plus_rows(
        cur,
        canonical_id=canonical_id,
        duplicate_id=duplicate_id,
        final_plu_code=pair.preferred_identifier_plu_code,
    )

    cur.execute("DELETE FROM skus WHERE id = %s::uuid", (duplicate_id,))
    cur.execute(
        """
        UPDATE skus
        SET sku_code = %s,
            legacy_code = %s,
            description = %s,
            long_description = %s,
            form_factor = %s,
            attributes = %s::jsonb,
            updated_at = NOW()
        WHERE id = %s::uuid
        """,
        (
            pair.preferred_identifier_sku_code,
            pair.supplier_code,
            pair.merged_description,
            pair.merged_long_description,
            pair.merged_form_factor,
            json.dumps(pair.merged_attributes, ensure_ascii=False),
            canonical_id,
        ),
    )


def _query_firestore_docs(fs_db, collection_path: str, field: str, value: str) -> list[Any]:
    return list(fs_db.collection(collection_path).where(field, "==", value).stream())


def _apply_firestore(pairs: list[OverlapPair]) -> dict[str, int]:
    from app.firestore import db as firestore_db  # noqa: E402

    stats = {
        "inventory_docs_updated": 0,
        "inventory_docs_deleted": 0,
        "stock_docs_updated": 0,
        "price_docs_updated": 0,
        "plus_docs_updated": 0,
        "plus_docs_deleted": 0,
        "top_level_skus_deleted": 0,
    }

    now = _now()
    for pair in pairs:
        canonical = pair.canonical
        duplicate = pair.duplicate

        canonical_inv_ref = firestore_db.collection(f"stores/{canonical.store_id}/inventory").document(canonical.sku_id)
        duplicate_inv_ref = firestore_db.collection(f"stores/{duplicate.store_id}/inventory").document(duplicate.sku_id)
        canonical_inv = canonical_inv_ref.get()
        if canonical_inv.exists:
            canonical_inv_ref.set(
                {
                    "sku_code": pair.preferred_identifier_sku_code,
                    "legacy_code": pair.supplier_code,
                    "description": pair.merged_description,
                    "form_factor": pair.merged_form_factor,
                    "updated_at": now,
                },
                merge=True,
            )
            stats["inventory_docs_updated"] += 1
        if duplicate_inv_ref.get().exists:
            duplicate_inv_ref.delete()
            stats["inventory_docs_deleted"] += 1

        for snap in _query_firestore_docs(firestore_db, f"stores/{duplicate.store_id}/stock", "sku_id", duplicate.sku_id):
            snap.reference.update({"sku_id": canonical.sku_id, "updated_at": now})
            stats["stock_docs_updated"] += 1

        for snap in _query_firestore_docs(firestore_db, f"stores/{duplicate.store_id}/prices", "sku_id", duplicate.sku_id):
            snap.reference.update({"sku_id": canonical.sku_id, "updated_at": now})
            stats["price_docs_updated"] += 1

        canonical_plus_docs = _query_firestore_docs(firestore_db, "plus", "sku_id", canonical.sku_id)
        duplicate_plus_docs = _query_firestore_docs(firestore_db, "plus", "sku_id", duplicate.sku_id)
        for snap in canonical_plus_docs:
            if (snap.to_dict() or {}).get("plu_code") != pair.preferred_identifier_plu_code:
                snap.reference.delete()
                stats["plus_docs_deleted"] += 1
        for snap in duplicate_plus_docs:
            data = snap.to_dict() or {}
            if data.get("plu_code") == pair.preferred_identifier_plu_code:
                snap.reference.set({"sku_id": canonical.sku_id, "updated_at": now}, merge=True)
                stats["plus_docs_updated"] += 1
            else:
                snap.reference.delete()
                stats["plus_docs_deleted"] += 1

        duplicate_top = firestore_db.collection("skus").document(duplicate.sku_id).get()
        if duplicate_top.exists:
            duplicate_top.reference.delete()
            stats["top_level_skus_deleted"] += 1

    return stats


def write_audit(prefix: Path, pairs: list[OverlapPair], summary: dict[str, Any]) -> tuple[Path, Path]:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = prefix.with_suffix(".json")
    lines_path = prefix.with_suffix(".jsonl")
    json_path.write_text(
        json.dumps(
            {"generated_at": _now().isoformat(), "summary": summary, "pairs": [asdict(pair) for pair in pairs]},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    with lines_path.open("w", encoding="utf-8") as handle:
        for pair in pairs:
            handle.write(json.dumps(asdict(pair), ensure_ascii=False, default=str) + "\n")
    return json_path, lines_path


def verify_postgres(conn: psycopg2.extensions.connection) -> dict[str, Any]:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute(
            """
            WITH rebuilt AS (
              SELECT sku_code, attributes->>'supplier_sku_code' AS supplier_code
              FROM skus
              WHERE attributes ? 'previous_sku_code'
            )
            SELECT COUNT(*) AS overlap_pairs
            FROM rebuilt r
            JOIN skus v ON v.legacy_code = r.supplier_code
            WHERE v.sku_code <> r.sku_code
            """
        )
        return dict(cur.fetchone())
    finally:
        cur.close()


def run(args: argparse.Namespace) -> None:
    audit_prefix = Path(args.audit_prefix)
    with psycopg2.connect(**_conn_kwargs(args.pg_url)) as conn:
        pairs = load_overlap_pairs(conn)
        summary = summarize(pairs)
        json_path, lines_path = write_audit(audit_prefix, pairs, summary)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        print(f"\nAudit files written:\n  {json_path}\n  {lines_path}")

        if not args.apply:
            print("\n(dry run — no Postgres or Firestore data changed. Re-run with --apply to persist.)")
            return

        with conn:
            with conn.cursor() as cur:
                for pair in pairs:
                    _apply_pair_postgres(cur, pair)

        firestore_stats = _apply_firestore(pairs)
        verify = verify_postgres(conn)
        print(
            "\nDedupe complete.\n"
            + json.dumps(
                {
                    "pair_count": len(pairs),
                    "firestore": firestore_stats,
                    "postgres_verify": verify,
                },
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deduplicate Hengwei supplier-code overlaps by merging rebuilt rows with pre-existing VE SKUs."
    )
    parser.add_argument("--pg-url", default=DEFAULT_PG_URL)
    parser.add_argument(
        "--audit-prefix",
        default=str(DEFAULT_EXPORT_DIR / f"hengwei_overlap_dedupe_{datetime.now().strftime('%Y%m%d')}"),
    )
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry-run)")
    return parser


def main() -> None:
    run(build_parser().parse_args())


if __name__ == "__main__":
    main()
