#!/usr/bin/env python3
"""
Export a CSV worksheet of every SKU in master_product_list.json that is
missing a retail_price, so the user can fill prices in Numbers/Excel and
send back. Pair with merge_retail_prices.py to apply edits.

Output: data/exports/retail_prices_to_fill.csv

Columns:
  sku_code, internal_code, supplier_id, description, product_type,
  material, size, qty_on_hand, cost_sgd, cost_cny, fx_rate,
  suggested_retail_sgd, set_sale_ready, notes

Fill `suggested_retail_sgd` with your price. Optional: change
`set_sale_ready` to N to keep the SKU off the next NEC export.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MASTER_JSON = REPO_ROOT / "data" / "master_product_list.json"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "exports" / "retail_prices_to_fill.csv"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--master", default=str(MASTER_JSON))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--include-priced", action="store_true",
        help="Include products that already have a retail_price (review mode)",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Include every product, not just launch-relevant ones",
    )
    args = parser.parse_args()

    data = json.loads(Path(args.master).read_text())
    products = data.get("products", [])

    def is_launch_relevant(p: dict) -> bool:
        return bool(p.get("sale_ready") or p.get("needs_retail_price"))

    rows = []
    for p in products:
        has_price = bool(p.get("retail_price") or p.get("price_incl_tax"))
        if has_price and not args.include_priced:
            continue
        if not args.all and not is_launch_relevant(p):
            continue
        cost_basis = p.get("cost_basis") or {}
        rows.append({
            "sku_code": p.get("sku_code") or "",
            "internal_code": p.get("internal_code") or "",
            "supplier_id": p.get("supplier_id") or "",
            "description": p.get("description") or "",
            "product_type": p.get("product_type") or "",
            "material": p.get("material") or "",
            "size": p.get("size") or "",
            "qty_on_hand": p.get("qty_on_hand") if p.get("qty_on_hand") is not None else "",
            "cost_sgd": p.get("cost_price") if p.get("cost_price") is not None else "",
            "cost_cny": cost_basis.get("source_amount") or "",
            "fx_rate": cost_basis.get("fx_rate_cny_per_sgd") or "",
            "current_retail_sgd": p.get("retail_price") or "",
            "suggested_retail_sgd": "",
            "set_sale_ready": "Y" if not p.get("sale_ready") else "",
            "notes": "",
        })

    rows.sort(key=lambda r: (r["supplier_id"], r["product_type"], r["sku_code"]))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else [
        "sku_code", "internal_code", "supplier_id", "description",
        "product_type", "material", "size", "qty_on_hand",
        "cost_sgd", "cost_cny", "fx_rate", "current_retail_sgd",
        "suggested_retail_sgd", "set_sale_ready", "notes",
    ]
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} rows to {out}")
    print()
    print("Open in Numbers/Excel, fill the `suggested_retail_sgd` column,")
    print("save as CSV, then run:")
    print("  python tools/scripts/merge_retail_prices.py --input <your-edited-csv>")


if __name__ == "__main__":
    main()
