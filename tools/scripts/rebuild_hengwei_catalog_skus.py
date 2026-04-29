#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "scripts"))

from build_master_product_list import extract_material, extract_product_type, generate_sku_code
from identifier_utils import (
    allocate_identifier_pair,
    is_valid_ean13,
    max_sku_sequence,
    max_valid_plu_sequence,
    validate_identifier_pair,
)

DEFAULT_PG_URL = "postgresql://retailsg:RetailSG2026Secure@127.0.0.1:5434/retailsg"
DEFAULT_CATALOG_JSON = REPO_ROOT / "docs" / "suppliers" / "hengweicraft" / "catalog_products.json"
DEFAULT_EXPORT_DIR = REPO_ROOT / "data" / "exports"

_GENERIC_DESCRIPTIONS = {
    "",
    "decoration",
    "decorations",
    "decor",
    "storage",
    "storage piece",
    "component",
    "piece",
}
_PREFIX_FORM_FACTOR = {
    "TRY": "Tray",
    "VAS": "Vase",
    "WAL": "Wall Art",
}
_PREFIX_MATERIAL = {
    "CPR": "Copper",
    "CRY": "Crystal",
    "MAL": "Malachite",
    "MAR": "Marble",
    "MIX": "Stone",
    "WOD": "Wood",
}
_ALLOWED_HOMEWARE_FORM_FACTORS = {
    "Decorative Object",
    "Tray",
    "Vase",
    "Wall Art",
    "Bookend",
    "Box",
    "Coaster",
    "Clock",
    "Candle Holder",
    "Mirror",
    "Lamp",
    "Figurine",
    "Sculpture",
    "Bowl",
}


@dataclass(frozen=True)
class LiveSkuRow:
    sku_id: str
    store_id: str
    store_code: str | None
    old_sku_code: str
    supplier_sku_code: str | None
    description: str
    long_description: str
    attributes: dict[str, Any]
    cost_price: float | None
    qty_on_hand: int


@dataclass(frozen=True)
class CatalogMatch:
    supplier_sku_code: str
    display_name: str | None
    size: str | None
    materials: str | None
    catalog_file: str | None
    sheet_name: str | None
    match_strategy: str


@dataclass(frozen=True)
class PlannedSku:
    sku_id: str
    store_id: str
    store_code: str | None
    old_sku_code: str
    supplier_sku_code: str | None
    new_sku_code: str
    plus_id: str
    new_plu_code: str
    description: str
    long_description: str
    form_factor: str
    material: str
    qty_on_hand: int
    catalog_file: str | None
    sheet_name: str | None
    match_strategy: str
    attributes: dict[str, Any]


FETCH_SQL = """
SELECT
    s.id::text AS sku_id,
    s.store_id::text AS store_id,
    st.store_code,
    s.sku_code AS old_sku_code,
    COALESCE(sp.supplier_sku_code, s.attributes->>'model') AS supplier_sku_code,
    COALESCE(s.description, '') AS description,
    COALESCE(s.long_description, '') AS long_description,
    s.attributes,
    s.cost_price::float8 AS cost_price,
    COALESCE((
        SELECT SUM(i.qty_on_hand)::int
        FROM inventories i
        WHERE i.sku_id = s.id
    ), 0) AS qty_on_hand
FROM skus s
LEFT JOIN stores st ON st.id = s.store_id
LEFT JOIN LATERAL (
    SELECT supplier_sku_code
    FROM supplier_products sp
    WHERE sp.sku_id = s.id
    ORDER BY sp.is_preferred DESC NULLS LAST, sp.created_at ASC NULLS LAST, sp.id
    LIMIT 1
) sp ON TRUE
WHERE s.sku_code NOT LIKE 'VE%'
ORDER BY s.sku_code
"""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).replace("\u3000", " ")
    text = text.replace("，", ", ").replace("、", ", ").replace("·", " ")
    text = text.replace("/", " / ")
    return re.sub(r"\s+", " ", text).strip()


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


def catalog_lookup_keys(code: str) -> list[str]:
    normalized = _normalize_text(code)
    if not normalized:
        return []

    keys = [normalized]

    ascii_match = re.match(r"[A-Za-z]+\d+[A-Za-z]?", normalized)
    if ascii_match:
        ascii_code = ascii_match.group(0)
        if ascii_code not in keys:
            keys.append(ascii_code)

    base_match = re.match(r"[A-Za-z]+\d+", normalized)
    if base_match:
        base_code = base_match.group(0)
        if base_code not in keys:
            keys.append(base_code)

    return keys


def build_catalog_index(catalog_products: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for product in catalog_products:
        for code in product.get("supplier_item_codes", []):
            normalized = _normalize_text(code)
            if normalized:
                index.setdefault(normalized, []).append(product)
        primary = _normalize_text(product.get("primary_supplier_item_code"))
        if primary:
            index.setdefault(primary, []).append(product)
    return index


def resolve_catalog_match(
    supplier_sku_code: str | None,
    catalog_index: dict[str, list[dict[str, Any]]],
) -> CatalogMatch | None:
    if not supplier_sku_code:
        return None

    normalized = _normalize_text(supplier_sku_code)
    for lookup_key in catalog_lookup_keys(normalized):
        matches = catalog_index.get(lookup_key) or []
        if not matches:
            continue
        match = matches[0]
        strategy = "exact" if lookup_key == normalized else "base_code"
        return CatalogMatch(
            supplier_sku_code=normalized,
            display_name=_normalize_text(match.get("display_name")) or None,
            size=_normalize_text(match.get("size")) or None,
            materials=_normalize_text(match.get("materials")) or None,
            catalog_file=_normalize_text(match.get("catalog_file")) or None,
            sheet_name=_normalize_text(match.get("sheet_name")) or None,
            match_strategy=strategy,
        )
    return None


def _material_fallback_from_code(old_sku_code: str) -> str:
    parts = old_sku_code.split("-")
    if len(parts) < 2:
        return ""
    return _PREFIX_MATERIAL.get(parts[1].upper(), "")


def derive_material(row: LiveSkuRow, catalog_match: CatalogMatch | None) -> str:
    material_source = " ".join(
        part
        for part in (
            catalog_match.materials if catalog_match else "",
            row.attributes.get("materials"),
            row.description,
            row.long_description,
        )
        if part
    )
    material = extract_material(_normalize_text(material_source))
    if material:
        return material
    return _material_fallback_from_code(row.old_sku_code) or "Stone"


def derive_form_factor(row: LiveSkuRow, catalog_match: CatalogMatch | None) -> str:
    prefix = row.old_sku_code.split("-")[0].upper() if row.old_sku_code else ""
    if prefix in _PREFIX_FORM_FACTOR:
        return _PREFIX_FORM_FACTOR[prefix]

    base_text = " ".join(
        part
        for part in (
            catalog_match.display_name if catalog_match else "",
            row.description,
            row.long_description,
            row.attributes.get("materials"),
        )
        if part
    )
    form_factor = extract_product_type(_normalize_text(base_text))
    if form_factor not in _ALLOWED_HOMEWARE_FORM_FACTORS:
        return "Decorative Object"
    return form_factor or "Decorative Object"


def derive_description(row: LiveSkuRow, catalog_match: CatalogMatch | None, form_factor: str) -> str:
    current = _normalize_text(row.description)
    catalog_name = _normalize_text(catalog_match.display_name) if catalog_match else ""

    if current.lower() not in _GENERIC_DESCRIPTIONS:
        description = current
    elif catalog_name and catalog_name.lower() not in _GENERIC_DESCRIPTIONS:
        description = catalog_name
    elif current:
        description = current
    elif catalog_name:
        description = catalog_name
    else:
        description = form_factor.lower()

    if description.lower() == "decoration" and form_factor != "Decorative Object":
        description = form_factor.lower()

    return description[:60]


def derive_long_description(row: LiveSkuRow, catalog_match: CatalogMatch | None, description: str) -> str:
    if row.long_description.strip():
        return row.long_description

    parts = [description.rstrip(".")]
    materials = _normalize_text(
        (catalog_match.materials if catalog_match else "") or row.attributes.get("materials")
    )
    size = _normalize_text((catalog_match.size if catalog_match else "") or row.attributes.get("size"))
    model = _normalize_text(row.supplier_sku_code or row.attributes.get("model"))
    catalog = _normalize_text(row.attributes.get("catalog") or (catalog_match.sheet_name if catalog_match else ""))

    if materials:
        parts.append(f"Materials: {materials}")
    if size:
        parts.append(f"Size: {size}")
    if model:
        parts.append(f"Model: {model}")
    if catalog:
        parts.append(f"Catalog: {catalog}")
    return ". ".join(parts).strip() + "."


def build_attributes(
    row: LiveSkuRow,
    catalog_match: CatalogMatch | None,
    *,
    new_sku_code: str,
    new_plu_code: str,
    form_factor: str,
    material: str,
) -> dict[str, Any]:
    attributes = dict(row.attributes)
    if row.supplier_sku_code:
        attributes["supplier_sku_code"] = row.supplier_sku_code
    if catalog_match:
        if catalog_match.materials:
            attributes["materials"] = catalog_match.materials
        if catalog_match.size:
            attributes["size"] = catalog_match.size
        if catalog_match.catalog_file:
            attributes["catalog_file"] = catalog_match.catalog_file
        if catalog_match.sheet_name:
            attributes["catalog_sheet_name"] = catalog_match.sheet_name
        attributes["catalog_match_strategy"] = catalog_match.match_strategy
        if catalog_match.display_name:
            attributes["catalog_display_name"] = catalog_match.display_name

    attributes["ve_padded_code"] = new_sku_code
    attributes["nec_plu"] = new_plu_code
    attributes["previous_sku_code"] = row.old_sku_code
    attributes["normalized_form_factor"] = form_factor
    attributes["normalized_material"] = material
    return attributes


def plan_rebuilds(
    rows: list[LiveSkuRow],
    catalog_index: dict[str, list[dict[str, Any]]],
    existing_sku_codes: set[str],
    existing_plus: set[str],
) -> list[PlannedSku]:
    next_seq = max(max_sku_sequence(existing_sku_codes), max_valid_plu_sequence(existing_plus)) + 1
    next_seq = max(next_seq, 1)
    plans: list[PlannedSku] = []

    for row in sorted(rows, key=lambda item: item.old_sku_code):
        catalog_match = resolve_catalog_match(row.supplier_sku_code, catalog_index)
        form_factor = derive_form_factor(row, catalog_match)
        material = derive_material(row, catalog_match)
        description = derive_description(row, catalog_match, form_factor)
        long_description = derive_long_description(row, catalog_match, description)
        supplier_basis = row.supplier_sku_code or row.old_sku_code
        new_sku_code, new_plu_code, next_seq = allocate_identifier_pair(
            lambda seq_num, basis=supplier_basis, mat=material, form=form_factor: generate_sku_code(
                basis,
                mat,
                form,
                seq_num,
            ),
            existing_sku_codes,
            existing_plus,
            next_seq,
        )
        validate_identifier_pair(new_sku_code, new_plu_code)
        attributes = build_attributes(
            row,
            catalog_match,
            new_sku_code=new_sku_code,
            new_plu_code=new_plu_code,
            form_factor=form_factor,
            material=material,
        )
        plans.append(
            PlannedSku(
                sku_id=row.sku_id,
                store_id=row.store_id,
                store_code=row.store_code,
                old_sku_code=row.old_sku_code,
                supplier_sku_code=row.supplier_sku_code,
                new_sku_code=new_sku_code,
                plus_id=str(uuid.uuid4()),
                new_plu_code=new_plu_code,
                description=description,
                long_description=long_description,
                form_factor=form_factor,
                material=material,
                qty_on_hand=row.qty_on_hand,
                catalog_file=catalog_match.catalog_file if catalog_match else None,
                sheet_name=catalog_match.sheet_name if catalog_match else None,
                match_strategy=catalog_match.match_strategy if catalog_match else "none",
                attributes=attributes,
            )
        )

    return plans


def summarize(rows: list[LiveSkuRow], plans: list[PlannedSku]) -> dict[str, Any]:
    return {
        "candidate_count": len(rows),
        "nonzero_inventory_rows": sum(1 for row in rows if row.qty_on_hand > 0),
        "match_strategy_counts": dict(Counter(plan.match_strategy for plan in plans).most_common()),
        "by_form_factor": dict(Counter(plan.form_factor for plan in plans).most_common(20)),
        "by_store": dict(Counter(plan.store_code or "UNKNOWN" for plan in plans).most_common()),
        "sample": [
            {
                "old_sku_code": plan.old_sku_code,
                "supplier_sku_code": plan.supplier_sku_code,
                "new_sku_code": plan.new_sku_code,
                "new_plu_code": plan.new_plu_code,
                "form_factor": plan.form_factor,
                "material": plan.material,
                "match_strategy": plan.match_strategy,
                "description": plan.description,
            }
            for plan in plans[:20]
        ],
    }


def write_audit_files(prefix: Path, plans: list[PlannedSku], summary: dict[str, Any]) -> tuple[Path, Path]:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    csv_path = prefix.with_suffix(".csv")
    json_path = prefix.with_suffix(".json")

    fieldnames = [
        "old_sku_code",
        "supplier_sku_code",
        "new_sku_code",
        "new_plu_code",
        "form_factor",
        "material",
        "qty_on_hand",
        "store_code",
        "catalog_file",
        "sheet_name",
        "match_strategy",
        "description",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for plan in plans:
            writer.writerow(
                {
                    "old_sku_code": plan.old_sku_code,
                    "supplier_sku_code": plan.supplier_sku_code or "",
                    "new_sku_code": plan.new_sku_code,
                    "new_plu_code": plan.new_plu_code,
                    "form_factor": plan.form_factor,
                    "material": plan.material,
                    "qty_on_hand": plan.qty_on_hand,
                    "store_code": plan.store_code or "",
                    "catalog_file": plan.catalog_file or "",
                    "sheet_name": plan.sheet_name or "",
                    "match_strategy": plan.match_strategy,
                    "description": plan.description,
                }
            )

    json_path.write_text(
        json.dumps(
            {
                "generated_at": _now_utc().isoformat(),
                "summary": summary,
                "plans": [asdict(plan) for plan in plans],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    return csv_path, json_path


async def fetch_rows(conn: asyncpg.Connection) -> list[LiveSkuRow]:
    rows = await conn.fetch(FETCH_SQL)
    return [
        LiveSkuRow(
            sku_id=str(row["sku_id"]),
            store_id=str(row["store_id"]),
            store_code=row["store_code"],
            old_sku_code=row["old_sku_code"],
            supplier_sku_code=_normalize_text(row["supplier_sku_code"]) or None,
            description=row["description"],
            long_description=row["long_description"],
            attributes=_coerce_attributes(row["attributes"]),
            cost_price=float(row["cost_price"]) if row["cost_price"] is not None else None,
            qty_on_hand=int(row["qty_on_hand"] or 0),
        )
        for row in rows
    ]


async def fetch_existing_identifiers(conn: asyncpg.Connection) -> tuple[set[str], set[str]]:
    sku_rows = await conn.fetch("SELECT sku_code FROM skus")
    plu_rows = await conn.fetch("SELECT plu_code FROM plus")
    sku_codes = {str(row["sku_code"]).strip() for row in sku_rows if row["sku_code"]}
    plus_codes = {str(row["plu_code"]).strip() for row in plu_rows if row["plu_code"]}
    return sku_codes, plus_codes


async def apply_postgres(conn: asyncpg.Connection, plans: list[PlannedSku]) -> None:
    for plan in plans:
        await conn.execute(
            """
            UPDATE skus
            SET sku_code = $1,
                description = $2,
                long_description = $3,
                form_factor = $4,
                attributes = $5::jsonb,
                updated_at = NOW()
            WHERE id = $6::uuid
            """,
            plan.new_sku_code,
            plan.description,
            plan.long_description,
            plan.form_factor,
            json.dumps(plan.attributes, ensure_ascii=False),
            plan.sku_id,
        )
        await conn.execute(
            """
            INSERT INTO plus (id, plu_code, sku_id, created_at)
            VALUES ($1::uuid, $2, $3::uuid, NOW())
            """,
            plan.plus_id,
            plan.new_plu_code,
            plan.sku_id,
        )


def apply_firestore(plans: list[PlannedSku]) -> dict[str, int]:
    from app.firestore import db as firestore_db  # noqa: E402

    now = _now_utc()
    batch = firestore_db.batch()
    operations = 0
    updates = {
        "inventory_docs_updated": 0,
        "inventory_docs_missing": 0,
        "plus_docs_created": 0,
    }

    def commit_if_needed() -> None:
        nonlocal batch, operations
        if operations and operations % 400 == 0:
            batch.commit()
            batch = firestore_db.batch()

    for plan in plans:
        inv_ref = firestore_db.collection(f"stores/{plan.store_id}/inventory").document(plan.sku_id)
        inv_snap = inv_ref.get()
        inv_payload = {
            "sku_code": plan.new_sku_code,
            "description": plan.description,
            "form_factor": plan.form_factor,
            "updated_at": now,
        }
        if inv_snap.exists:
            batch.set(inv_ref, inv_payload, merge=True)
            updates["inventory_docs_updated"] += 1
            operations += 1
            commit_if_needed()
        else:
            updates["inventory_docs_missing"] += 1

        plus_ref = firestore_db.collection("plus").document(plan.plus_id)
        batch.set(
            plus_ref,
            {
                "id": plan.plus_id,
                "plu_code": plan.new_plu_code,
                "sku_id": plan.sku_id,
                "created_at": now,
            },
        )
        updates["plus_docs_created"] += 1
        operations += 1
        commit_if_needed()

    if operations % 400 != 0 and operations > 0:
        batch.commit()

    return updates


async def verify_postgres(conn: asyncpg.Connection, plans: list[PlannedSku]) -> dict[str, Any]:
    sku_ids = [plan.sku_id for plan in plans]
    remaining_non_ve = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM skus
        WHERE id = ANY($1::uuid[])
          AND sku_code NOT LIKE 'VE%'
        """,
        sku_ids,
    )
    plus_rows = await conn.fetch(
        """
        SELECT s.sku_code, p.plu_code
        FROM plus p
        JOIN skus s ON s.id = p.sku_id
        WHERE s.id = ANY($1::uuid[])
        """,
        sku_ids,
    )
    invalid_plus = [
        {"sku_code": row["sku_code"], "plu_code": row["plu_code"]}
        for row in plus_rows
        if not is_valid_ean13(str(row["plu_code"]))
    ]
    return {
        "remaining_non_ve": int(remaining_non_ve or 0),
        "plus_rows": len(plus_rows),
        "invalid_plus_count": len(invalid_plus),
        "invalid_plus_sample": invalid_plus[:10],
    }


def verify_firestore(plans: list[PlannedSku]) -> dict[str, int]:
    from app.firestore import db as firestore_db  # noqa: E402

    old_inventory_codes = 0
    plus_missing = 0
    for plan in plans:
        inv_snap = firestore_db.collection(f"stores/{plan.store_id}/inventory").document(plan.sku_id).get()
        if inv_snap.exists and (inv_snap.to_dict() or {}).get("sku_code") == plan.old_sku_code:
            old_inventory_codes += 1
        plus_snap = firestore_db.collection("plus").document(plan.plus_id).get()
        if not plus_snap.exists:
            plus_missing += 1

    return {
        "inventory_docs_still_old_code": old_inventory_codes,
        "plus_docs_missing": plus_missing,
    }


async def run(args: argparse.Namespace) -> None:
    catalog_data = json.loads(Path(args.catalog_json).read_text(encoding="utf-8"))
    catalog_index = build_catalog_index(catalog_data.get("products", []))

    conn = await asyncpg.connect(args.pg_url)
    try:
        rows = await fetch_rows(conn)
        existing_sku_codes, existing_plus = await fetch_existing_identifiers(conn)
        plans = plan_rebuilds(rows, catalog_index, existing_sku_codes, existing_plus)
        summary = summarize(rows, plans)
        audit_prefix = Path(args.audit_prefix)
        csv_path, json_path = write_audit_files(audit_prefix, plans, summary)

        print(json.dumps(summary, indent=2, ensure_ascii=False))
        print(f"\nAudit files written:\n  {csv_path}\n  {json_path}")

        if not args.apply:
            print("\n(dry run — no Postgres or Firestore data changed. Re-run with --apply to persist.)")
            return

        async with conn.transaction():
            await apply_postgres(conn, plans)

        firestore_updates = apply_firestore(plans)
        pg_verify = await verify_postgres(conn, plans)
        fs_verify = verify_firestore(plans)

        print(
            "\nRebuild complete.\n"
            + json.dumps(
                {
                    "postgres_verify": pg_verify,
                    "firestore_updates": firestore_updates,
                    "firestore_verify": fs_verify,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    finally:
        await conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rebuild non-VE Hengwei catalog SKUs into aligned VE sku_code/plu pairs in place."
    )
    parser.add_argument("--pg-url", default=DEFAULT_PG_URL)
    parser.add_argument("--catalog-json", default=str(DEFAULT_CATALOG_JSON))
    parser.add_argument(
        "--audit-prefix",
        default=str(DEFAULT_EXPORT_DIR / f"hengwei_catalog_rebuild_{datetime.now().strftime('%Y%m%d')}"),
        help="Path prefix for the audit CSV/JSON outputs.",
    )
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry-run)")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
