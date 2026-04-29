#!/usr/bin/env python3
"""
Ingest supplier order line-items into ``data/master_product_list.json``.

For every ``supplier_item_code`` in ``docs/suppliers/<name>/orders/*.json``
that is NOT already present in the master list, we generate a new product
row following the existing naming conventions:

    sku_code  : VE + {3-char product_type code} + {4-char material code} + {7-digit seq}
    nec_plu   : next available 13-digit numeric barcode (starts with '2')
    description : "{Material} {Product Type} ({size})"  (<=60 chars)
    cost_price  : unit_cost converted from order currency to SGD
    qty_on_hand : SUM of all order quantities for this code

Dry run is the default. Pass ``--apply`` to write the updated master list.

Usage:
  python ingest_supplier_orders.py --supplier hengweicraft
  python ingest_supplier_orders.py --supplier hengweicraft --apply
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from identifier_utils import (
    allocate_identifier_pair,
    max_sku_sequence,
    validate_identifier_pair,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MASTER_PATH = REPO_ROOT / "data" / "master_product_list.json"
SUPPLIERS_DIR = REPO_ROOT / "docs" / "suppliers"

# Default fallback when a Hengwei order doesn't record its own FX rate.
DEFAULT_FX = {
    "CNY": 5.34,   # CNY per SGD (Hengwei order 364-365 cash rate)
    "HKD": 5.80,
    "USD": 0.74,
    "SGD": 1.0,
}

LOCATION_NORMALIZATION = {
    "workshop": "warehouse",
    "manufacturing": "warehouse",
    "factory": "warehouse",
}

# ── Canonical short codes (mirror existing master list) ──────────────────────

PRODUCT_TYPE_CODE = {
    "Figurine":          "FIG",
    "Sculpture":         "SCU",
    "Bookend":           "BKE",
    "Bowl":              "BWL",
    "Vase":              "DEC",   # No VAS code in master — group under DEC
    "Box":               "BOX",
    "Tray":              "DEC",
    "Decorative Object": "DEC",
    "Wall Art":          "WAL",
    "Gift Set":          "DEC",
}

MATERIAL_CODE = {
    "malachite": "MALA",
    "copper":    "COPP",
    "marble":    "MARB",
    "crystal":   "CRYS",
    "gypsum":    "STON",
    "dolomite":  "STON",
    "stone":     "STON",
    "acrylic":   "XXXX",
    "tin":       "XXXX",
    "rattan":    "RATT",
}

# Override product_type for specific supplier codes (heuristic supplement).
PRODUCT_TYPE_OVERRIDES = {
    "hengweicraft": {
        "A507": "Decorative Object",  # "Napkin buckle"
        "A508": "Decorative Object",
    },
}

# Default product_type when no override and no catalog-derived hint.
DEFAULT_PRODUCT_TYPE_BY_SUPPLIER = {
    "hengweicraft": "Sculpture",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def primary_material(mat_desc: str) -> tuple[str, str]:
    """Return (pretty material, 4-char code)."""
    if not mat_desc:
        return "Stone", "STON"
    first = mat_desc.split(",", 1)[0].strip()
    lower_full = mat_desc.lower()
    # Priority order: look for the most specific/distinctive material first
    for kw in ("malachite", "marble", "gypsum", "rattan", "crystal", "copper", "dolomite", "stone", "acrylic", "tin"):
        if kw in lower_full:
            pretty = kw.capitalize()
            code = MATERIAL_CODE.get(kw, "XXXX")
            return pretty, code
    # Fallback: capitalise the first fragment
    return first or "Stone", "STON"


def resolve_product_type(supplier: str, supplier_code: str, line: dict[str, Any]) -> str:
    override = PRODUCT_TYPE_OVERRIDES.get(supplier, {}).get(supplier_code)
    if override:
        return override
    # Cheap keyword hint from description/note
    hint = " ".join(str(line.get(k) or "") for k in ("display_name", "note", "material_description")).lower()
    if "bookend" in hint:
        return "Bookend"
    if "bowl" in hint:
        return "Bowl"
    if "vase" in hint:
        return "Vase"
    if "box" in hint:
        return "Box"
    if "tray" in hint:
        return "Tray"
    if "figurine" in hint:
        return "Figurine"
    if "wall" in hint:
        return "Wall Art"
    return DEFAULT_PRODUCT_TYPE_BY_SUPPLIER.get(supplier, "Sculpture")


def next_sku_code(
    product_type: str,
    mat_code: str,
    existing_codes: set[str],
    existing_plus: set[str],
    next_seq: int,
) -> tuple[str, str, int]:
    pt_code = PRODUCT_TYPE_CODE.get(product_type, "DEC")
    return allocate_identifier_pair(
        lambda seq: f"VE{pt_code}{mat_code}{seq:07d}",
        existing_codes,
        existing_plus,
        next_seq,
    )


def build_description(material: str, product_type: str, size: str | None) -> str:
    size_s = f" ({size})" if size else ""
    base = f"{material} {product_type}{size_s}".strip()
    return base[:60]


def build_long_description(line: dict[str, Any]) -> str:
    parts = []
    if line.get("material_description"):
        parts.append(f"Materials: {line['material_description']}")
    if line.get("size"):
        parts.append(f"Size: {line['size']}")
    if line.get("note"):
        parts.append(f"Note: {line['note']}")
    return " | ".join(parts)[:500]


def convert_to_sgd(amount: float, currency: str, order: dict[str, Any]) -> float:
    """Convert unit_cost to SGD using the order's own FX rate where possible."""
    for pay in order.get("payment_breakdown") or []:
        rate = pay.get("reported_fx_rate_cny_per_sgd")
        if rate and pay.get("currency") == currency:
            return round(amount / rate, 2)
    fallback = DEFAULT_FX.get(currency, 1.0)
    if currency == "SGD":
        return round(amount, 2)
    # treat DEFAULT_FX values as "{currency} per SGD"
    return round(amount / fallback, 2)


# ── Core ingest ──────────────────────────────────────────────────────────────

def load_supplier_orders(supplier: str) -> list[dict[str, Any]]:
    supplier_dir = SUPPLIERS_DIR / supplier
    orders_dir = supplier_dir / "orders"
    if not orders_dir.is_dir():
        raise FileNotFoundError(f"No orders directory: {orders_dir}")
    orders: list[dict[str, Any]] = []
    for f in sorted(orders_dir.glob("*.json")):
        orders.append(json.loads(f.read_text()))
    return orders


def collect_lines_by_code(orders: list[dict[str, Any]]) -> dict[str, list[tuple[dict, dict]]]:
    """Group (line_item, order) tuples by supplier_item_code."""
    bycode: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for order in orders:
        for li in order.get("line_items", []):
            code = li.get("supplier_item_code")
            if code:
                bycode[code].append((li, order))
    return bycode


def build_new_product(
    supplier_code: str,
    lines: list[tuple[dict, dict]],
    supplier_name: str,
    supplier: str,
    existing_sku_codes: set[str],
    existing_plus: set[str],
    next_seq: int,
) -> tuple[dict[str, Any], int]:
    # Canonical line (first occurrence) gives size/material; qty is summed.
    canonical_line, canonical_order = lines[0]
    material_desc = canonical_line.get("material_description") or ""
    size = canonical_line.get("size")
    mat_name, mat_code = primary_material(material_desc)
    product_type = resolve_product_type(supplier, supplier_code, canonical_line)

    sku_code, plu, next_seq = next_sku_code(
        product_type,
        mat_code,
        existing_sku_codes,
        existing_plus,
        next_seq,
    )
    validate_identifier_pair(sku_code, plu)

    # Sum quantity across ALL orders for this code
    total_qty = sum(int(li.get("quantity") or 0) for li, _ in lines)

    # Cost = canonical unit_cost converted to SGD (using canonical_order's fx)
    currency = canonical_order.get("currency", "CNY")
    unit_cost = canonical_line.get("unit_cost_cny") or canonical_line.get("unit_cost") or 0
    cost_sgd = convert_to_sgd(float(unit_cost), currency, canonical_order)

    stocking_location = (
        (canonical_order.get("inventory_movement") or {}).get("current_location", "")
        .lower().replace(" ", "_")
    )
    stocking_location = LOCATION_NORMALIZATION.get(stocking_location, stocking_location)

    description = build_description(mat_name, product_type, size)
    long_desc = build_long_description(canonical_line)

    product = {
        "id": f"ingest_{supplier}_{supplier_code.lower()}",
        "internal_code": supplier_code,
        "sku_code": sku_code,
        "nec_plu": plu,
        "description": description,
        "long_description": long_desc,
        "product_type": product_type,
        "category": "",
        "material": mat_name,
        "amazon_sku": "",
        "google_product_id": "",
        "google_product_category": "",
        "cost_price": cost_sgd,
        "retail_price": None,
        "qty_on_hand": total_qty,
        "raw_names": [material_desc] if material_desc else [],
        "mention_count": len(lines),
        "inventory_type": "purchased",
        "sourcing_strategy": "supplier_premade",
        "inventory_category": "finished_for_sale",
        "sale_ready": False,
        "block_sales": False,
        "stocking_status": "in_stock",
        "stocking_location": stocking_location,
        "use_stock": True,
        "sources": [f"supplier:{supplier_name}"],
    }
    return product, next_seq


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--supplier", required=True, help="Supplier folder name under docs/suppliers/")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry-run)")
    parser.add_argument("--master", default=str(MASTER_PATH), help="Path to master_product_list.json")
    args = parser.parse_args()

    master_path = Path(args.master)
    master = json.loads(master_path.read_text())
    products: list[dict[str, Any]] = master["products"]

    # Indexes
    by_internal: dict[str, dict] = {
        p["internal_code"]: p for p in products if p.get("internal_code")
    }
    existing_sku_codes: set[str] = {p["sku_code"] for p in products if p.get("sku_code")}
    existing_plus: set[str] = {str(p["nec_plu"]) for p in products if p.get("nec_plu")}

    # Next available aligned identifier sequence
    seqs = [int(p["sku_code"][9:]) for p in products
            if (p.get("sku_code") or "").startswith("VE")
            and len(p.get("sku_code") or "") >= 15
            and p["sku_code"][9:].isdigit()]
    next_seq = max(max_sku_sequence(p.get("sku_code") for p in products), max(seqs, default=0)) + 1
    next_seq = max(next_seq, 1)

    # Load supplier orders
    orders = load_supplier_orders(args.supplier)
    supplier_name = next((o.get("supplier_name") for o in orders if o.get("supplier_name")), args.supplier)
    lines_by_code = collect_lines_by_code(orders)

    # Decide what's new
    missing = {code: lines for code, lines in lines_by_code.items() if code not in by_internal}
    matched = {code: lines for code, lines in lines_by_code.items() if code in by_internal}

    print(f"Supplier         : {args.supplier} ({supplier_name})")
    print(f"Orders parsed    : {len(orders)}")
    print(f"Unique codes     : {len(lines_by_code)}")
    print(f"Already in master: {len(matched)}")
    print(f"To ingest (new)  : {len(missing)}")
    print(f"Next identifier seq: {next_seq:07d}")
    print()

    # Build new rows
    new_rows: list[dict[str, Any]] = []
    for code in sorted(missing.keys()):
        prod, next_seq = build_new_product(
            code, missing[code], supplier_name, args.supplier,
            existing_sku_codes, existing_plus, next_seq,
        )
        new_rows.append(prod)

    seen_sku_codes: set[str] = set()
    seen_plus: set[str] = set()
    for product in products + new_rows:
        sku_code = str(product.get("sku_code") or "").strip()
        nec_plu = str(product.get("nec_plu") or "").strip()
        if not sku_code or not nec_plu:
            continue
        validate_identifier_pair(sku_code, nec_plu)
        if sku_code in seen_sku_codes:
            raise ValueError(f"Duplicate sku_code detected while preparing ingest: {sku_code}")
        if nec_plu in seen_plus:
            raise ValueError(f"Duplicate nec_plu detected while preparing ingest: {nec_plu}")
        seen_sku_codes.add(sku_code)
        seen_plus.add(nec_plu)

    # Print plan
    print(f"{'supplier_code':14s}  {'sku_code':18s}  {'nec_plu':14s}  {'type':18s}  {'qty':>4}  {'cost$':>7}  desc")
    print("-" * 110)
    for p in new_rows:
        print(
            f"{p['internal_code']:14s}  {p['sku_code']:18s}  {p['nec_plu']:14s}  "
            f"{p['product_type']:18s}  {p['qty_on_hand']:4d}  {p['cost_price']:7.2f}  {p['description']}"
        )

    if not args.apply:
        print("\n(dry run — no files written. Re-run with --apply to persist.)")
        return

    # Apply: append and sort
    products.extend(new_rows)
    products.sort(key=lambda x: x.get("sku_code", ""))
    master_path.write_text(json.dumps(master, indent=2, ensure_ascii=False) + "\n")
    print(f"\nWrote {len(new_rows)} new products to {master_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
