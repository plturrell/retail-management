#!/usr/bin/env python3
"""
Merge a filled-in retail-price CSV back into master_product_list.json.

Reads each row from the CSV, matches by sku_code, and:
  * sets retail_price = suggested_retail_sgd (if non-empty and numeric)
  * if set_sale_ready in {Y, y, yes, TRUE, 1}: marks sale_ready = True
    and clears needs_retail_price/needs_review flags
  * appends notes to the product (under retail_price_note)

Skips rows with no suggested_retail_sgd. Writes a backup before saving.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MASTER_JSON = REPO_ROOT / "data" / "master_product_list.json"
DEFAULT_INPUT = REPO_ROOT / "data" / "exports" / "retail_prices_to_fill.csv"

TRUTHY = {"y", "yes", "true", "1"}


def parse_price(s: str) -> float | None:
    if s is None:
        return None
    txt = str(s).strip().replace("$", "").replace("S$", "").replace(",", "")
    if not txt:
        return None
    try:
        v = float(txt)
        return v if v > 0 else None
    except ValueError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--master", default=str(MASTER_JSON))
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    master_path = Path(args.master)
    csv_path = Path(args.input)

    data = json.loads(master_path.read_text())
    products = data.get("products", [])
    by_sku = {str(p.get("sku_code") or "").strip(): p for p in products if p.get("sku_code")}

    updated = 0
    activated = 0
    skipped_no_price = 0
    not_found = []

    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sku = (row.get("sku_code") or "").strip()
            if not sku:
                continue
            prod = by_sku.get(sku)
            if not prod:
                not_found.append(sku)
                continue
            price = parse_price(row.get("suggested_retail_sgd"))
            if price is None:
                skipped_no_price += 1
                continue
            prod["retail_price"] = price
            prod["retail_price_set_at"] = datetime.utcnow().isoformat() + "Z"
            note = (row.get("notes") or "").strip()
            if note:
                prod["retail_price_note"] = note
            if (row.get("set_sale_ready") or "").strip().lower() in TRUTHY:
                if not prod.get("sale_ready"):
                    activated += 1
                prod["sale_ready"] = True
                prod.pop("needs_retail_price", None)
                prod.pop("needs_review", None)
            updated += 1

    print(f"Updated retail_price on : {updated} SKUs")
    print(f"Newly sale_ready=true   : {activated} SKUs")
    print(f"Rows with no price      : {skipped_no_price}")
    if not_found:
        print(f"\nWARNING  {len(not_found)} sku_code values from CSV not found in master:")
        for s in not_found[:20]:
            print(f"  {s}")

    if args.dry_run:
        print("\n[dry-run] no changes written.")
        return

    backup = master_path.with_suffix(master_path.suffix + ".bak")
    backup.write_text(master_path.read_text())
    data.setdefault("metadata", {})["last_modified"] = datetime.utcnow().isoformat() + "Z"
    data["metadata"]["last_modified_by"] = "merge_retail_prices.py"
    master_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nWrote {master_path}")
    print(f"Backup: {backup}")


if __name__ == "__main__":
    main()
