#!/usr/bin/env python3
"""
Merge unmatched Hengwei Craft order line items into data/master_product_list.json.

For each supplier_item_code from the order JSONs that has no existing product
in the master list, allocate a fresh SKU + NEC PLU pair (sharing the same
7-digit sequence per the bulletproof identifier_utils method) and write a
new product entry. Existing entries are left alone.

cost_price is converted from CNY at the fixed historical rate of 5.34 CNY/SGD.
retail_price is left null -- the user fills it in via the CSV the next step
of the pipeline produces.

Run:
    python tools/scripts/add_hengwei_skus_to_master.py
    python tools/scripts/add_hengwei_skus_to_master.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "scripts"))

from identifier_utils import (
    aligned_nec_plu_for_sku,
    allocate_identifier_pair,
    max_sku_sequence,
)

MASTER_JSON = REPO_ROOT / "data" / "master_product_list.json"
ORDER_DIR = REPO_ROOT / "docs" / "suppliers" / "hengweicraft" / "orders"
SUPPLIER_ID = "CN-001"
SUPPLIER_NAME = "Hengwei Craft"
FX_CNY_PER_SGD = 5.34
STOCKING_LOCATION = "jewel_changi"


def detect_material(material_desc: str) -> tuple[str, str]:
    """Return (4-char abbrev, human label) inferred from supplier text."""
    m = (material_desc or "").lower()
    if "crystal" in m:
        return "CRYS", "Crystal"
    if "malachite" in m:
        return "MALA", "Malachite"
    if "fluorite" in m:
        return "FLUO", "Fluorite"
    if "marble" in m:
        return "MARB", "Marble"
    if "gypsum" in m:
        return "GYPS", "Gypsum"
    if "shangri" in m:
        return "STON", "Shangri-la Stone"
    if "mineral" in m or "stone" in m or "dolomite" in m:
        return "STON", "Mineral Stone"
    return "MIXD", "Mixed Materials"


def detect_product_type(size: str, material_desc: str, note: str) -> tuple[str, str, str]:
    """Return (3-char abbrev, type slug, human label)."""
    if "napkin" in (note or "").lower():
        return "NAP", "Napkin Holder", "Napkin Holder"
    dims = re.findall(r"\d+(?:\.\d+)?", size or "")
    if len(dims) >= 3:
        try:
            d = sorted(float(x) for x in dims)
            # Tall narrow → bookend (a typical bookend is ~10cm wide and 30cm+ tall)
            if d[-1] >= 30 and d[0] <= 15:
                return "BKE", "Bookend", "Bookend"
        except ValueError:
            pass
    return "DEC", "Decorative Object", "Decorative Object"


def short_size(size: str) -> str:
    return (size or "").replace(" ", "").replace("*", "x")


def synth_description(type_label: str, material_label: str, size: str, code: str) -> str:
    parts = [f"{type_label} in {material_label}"]
    s = short_size(size)
    if s:
        parts.append(f"{s} cm")
    parts.append(f"[{code}]")
    return " — ".join(parts[:-1]) + f"  ({parts[-1]})"


def synth_long_description(type_label: str, material_label: str, size: str, full_material: str) -> str:
    s = short_size(size)
    parts = [f"{type_label} crafted from {material_label.lower()}."]
    if full_material and full_material.lower() != material_label.lower():
        parts.append(f"Materials: {full_material}.")
    if s:
        parts.append(f"Dimensions: {s} cm.")
    parts.append("Hand-finished. Imported from China.")
    return " ".join(parts)


def collect_order_items() -> list[dict]:
    items = []
    for f in sorted(ORDER_DIR.glob("*.json")):
        order = json.loads(f.read_text())
        for li in order.get("line_items", []):
            code = li.get("supplier_item_code")
            if not code:
                continue  # skip Guardian-artwork-style unidentified lines
            items.append({
                "code": code,
                "unit_cost_cny": li.get("unit_cost_cny"),
                "quantity": li.get("quantity") or 0,
                "size": li.get("size") or "",
                "material_description": li.get("material_description") or "",
                "note": li.get("note") or "",
                "order_number": order.get("order_number"),
                "order_date": order.get("order_date"),
            })
    return items


def existing_codes(products: list[dict]) -> set[str]:
    seen = set()
    for p in products:
        ic = p.get("internal_code")
        if ic:
            seen.add(str(ic).strip())
    return seen


def existing_sku_codes(products: list[dict]) -> set[str]:
    return {str(p["sku_code"]).strip() for p in products if p.get("sku_code")}


def existing_plus(products: list[dict]) -> set[str]:
    out = set()
    for p in products:
        for f in ("nec_plu", "plu_code"):
            v = p.get(f)
            if v:
                out.add(str(v).strip())
    return out


def make_sku_factory(type_abbr: str, mat_abbr: str):
    """SKU code follows existing convention: VE{TYPE}{MATL}{seq:07d}."""
    def factory(seq: int) -> str:
        return f"VE{type_abbr}{mat_abbr}{seq:07d}"
    return factory


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--master", default=str(MASTER_JSON))
    args = parser.parse_args()

    master_path = Path(args.master)
    data = json.loads(master_path.read_text())
    products: list[dict] = data.get("products", [])

    have_codes = existing_codes(products)
    sku_set = existing_sku_codes(products)
    plu_set = existing_plus(products)
    next_seq = max(max_sku_sequence(sku_set), 0) + 1

    order_items = collect_order_items()
    new_entries = []
    skipped = []

    for it in order_items:
        if it["code"] in have_codes:
            skipped.append(it["code"])
            continue

        mat_abbr, mat_label = detect_material(it["material_description"])
        type_abbr, type_slug, type_label = detect_product_type(it["size"], it["material_description"], it["note"])

        sku_factory = make_sku_factory(type_abbr, mat_abbr)
        sku_code, plu_code, next_seq = allocate_identifier_pair(
            sku_factory, sku_set, plu_set, next_seq
        )

        cost_sgd = round(it["unit_cost_cny"] / FX_CNY_PER_SGD, 2) if it["unit_cost_cny"] else None
        prod_id = f"hengwei-{it['code'].lower().replace('紫晶','zijing').replace('绿','lv')}"

        entry = {
            "id": prod_id,
            "internal_code": it["code"],
            "sku_code": sku_code,
            "description": synth_description(type_label, mat_label, it["size"], it["code"]),
            "long_description": synth_long_description(type_label, mat_label, it["size"], it["material_description"]),
            "material": mat_label,
            "product_type": type_label,
            "category": "Home Decor",
            "amazon_sku": f"VE-{mat_abbr}-{type_abbr}-{it['code']}",
            "google_product_id": f"online:en:SG:{sku_code}",
            "google_product_category": "Home & Garden > Decor",
            "nec_plu": plu_code,
            "cost_price": cost_sgd,
            "cost_currency": "SGD",
            "cost_basis": {
                "source_currency": "CNY",
                "source_amount": it["unit_cost_cny"],
                "fx_rate_cny_per_sgd": FX_CNY_PER_SGD,
            },
            "retail_price": None,
            "qty_on_hand": it["quantity"],
            "supplier_id": SUPPLIER_ID,
            "supplier_name": SUPPLIER_NAME,
            "supplier_item_code": it["code"],
            "source_orders": [it["order_number"]],
            "sources": [f"hengwei_order_{it['order_number']}"],
            "raw_names": [],
            "mention_count": 1,
            "inventory_type": "purchased",
            "sourcing_strategy": "supplier_premade",
            "inventory_category": "finished_for_sale",
            "sale_ready": False,
            "block_sales": False,
            "stocking_status": "in_stock",
            "stocking_location": STOCKING_LOCATION,
            "use_stock": True,
            "size": it["size"],
            "added_at": datetime.utcnow().isoformat() + "Z",
            "added_via": "add_hengwei_skus_to_master.py",
            "needs_review": True,
            "needs_retail_price": True,
        }
        new_entries.append(entry)

    print(f"Order line items considered : {len(order_items)}")
    print(f"Already in master JSON       : {len(skipped)}")
    print(f"New SKUs to create           : {len(new_entries)}")
    print()
    for e in new_entries:
        cost = e["cost_price"]
        cost_str = f"S${cost:.2f}" if cost is not None else "    n/a"
        print(f"  {e['sku_code']}  PLU {e['nec_plu']}  {cost_str}  {e['internal_code']:10s}  {e['description'][:55]}")

    # sanity: every new sku/plu pair must be aligned
    for e in new_entries:
        if aligned_nec_plu_for_sku(e["sku_code"]) != e["nec_plu"]:
            raise RuntimeError(f"PLU/SKU misaligned for {e['sku_code']} / {e['nec_plu']}")

    if args.dry_run:
        print("\n[dry-run] no changes written.")
        return

    products.extend(new_entries)
    data["products"] = products
    data.setdefault("metadata", {})["last_modified"] = datetime.utcnow().isoformat() + "Z"
    data["metadata"]["last_modified_by"] = "add_hengwei_skus_to_master.py"

    backup = master_path.with_suffix(master_path.suffix + ".bak")
    backup.write_text(master_path.read_text())
    master_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(new_entries)} new SKUs to {master_path}")
    print(f"Backup: {backup}")


if __name__ == "__main__":
    main()
