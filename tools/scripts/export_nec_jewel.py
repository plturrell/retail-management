#!/usr/bin/env python3
"""
Export sellable catalogue → Jewel NEC POS Master Data Excel workbook.

Pulls from the live Firestore operational database by default. A SKU is
*sellable* when ALL of:
  * ``sale_ready = true``
  * ``status = 'active'`` and ``block_sales = false``
  * an active price doc exists (valid_from <= today <= valid_to)
  * a description is present
  * a PLU (NEC barcode) doc exists

Everything else is excluded and reported as a gap so the operator can
complete the missing data before re-running.

Output sheets: CATG, SKU v2, PLU, PRICE, PROMO, INVDETAILS

Usage::

  # Default -- read from Firestore
  python export_nec_jewel.py

  # Legacy -- read from the JSON master list (no Firestore required)
  python export_nec_jewel.py --from-json

Filters:
  --brand "VICTORIA ENSO"    only products for this brand (default)
  --store JEWEL-01           only SKUs stocked at this store
  --include-drafts           bypass the sale_ready gate (debug only)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

DEFAULT_INPUT = "data/master_product_list.json"
DEFAULT_OUTPUT = "data/exports/nec_jewel_master_data.xlsx"


def load_from_json(
    input_path: Path,
    location_filter: str = "",
    sale_ready_only: bool = True,
) -> list[dict[str, Any]]:
    data = json.loads(input_path.read_text())
    all_products = data.get("products", [])
    print(f"Loaded {len(all_products)} products from {input_path.name}")

    products = all_products
    if location_filter:
        products = [
            p for p in products
            if p.get("stocking_location", "").lower() == location_filter.lower()
        ]
        print(f"  Filtered by location='{location_filter}': {len(products)} products")
    if sale_ready_only:
        products = [p for p in products if p.get("sale_ready")]
        print(f"  Filtered by sale_ready=True: {len(products)} products")
    return products


def print_data_gaps(products: list[dict[str, Any]]) -> None:
    no_cost = [p for p in products if not p.get("cost_price")]
    no_plu = [p for p in products if not (p.get("nec_plu") or p.get("plu_code"))]
    no_price = [p for p in products if not (p.get("retail_price") or p.get("price_incl_tax"))]
    if no_price:
        print(f"\n  WARNING  MISSING RETAIL PRICE: {len(no_price)} products (no PRICE row)")
    if no_plu:
        print(f"  WARNING  MISSING PLU/BARCODE:  {len(no_plu)} products (no PLU row)")
    if no_cost:
        print(f"  WARNING  MISSING COST PRICE:   {len(no_cost)} products")


def print_excluded_report(excluded: list[dict[str, Any]]) -> None:
    if not excluded:
        return
    not_sale_ready = [e for e in excluded if not e.get("sale_ready")]
    no_price = [e for e in excluded if not e.get("has_price")]
    no_plu = [e for e in excluded if not e.get("has_plu")]

    print(f"\n  EXCLUDED from NEC POS export: {len(excluded)} SKUs")
    if not_sale_ready:
        print(f"    sale_ready=false : {len(not_sale_ready)}")
    if no_price:
        print(f"    no active price  : {len(no_price)}")
    if no_plu:
        print(f"    no PLU/barcode   : {len(no_plu)}")

    if not_sale_ready:
        print("\n    Not sale-ready (first 10):")
        for e in not_sale_ready[:10]:
            flags = []
            if not e.get("has_price"):
                flags.append("no-price")
            if not e.get("has_plu"):
                flags.append("no-plu")
            flag_str = f"  [{', '.join(flags)}]" if flags else ""
            print(f"      {e['sku_code']:16s}  {(e.get('description') or '')[:45]}{flag_str}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Jewel NEC POS Master Data (Excel)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output Excel file path")
    parser.add_argument(
        "--from-json", action="store_true",
        help="Read from JSON master list instead of Firestore (legacy mode)",
    )
    parser.add_argument("--input", default=DEFAULT_INPUT, help="[JSON mode] Master product list JSON")
    parser.add_argument("--location", default="", help="[JSON mode] Filter by stocking_location")
    parser.add_argument("--brand", default=None, help="Brand name to export (default: VICTORIA ENSO)")
    parser.add_argument("--store", default=None, help="Store code filter (e.g. JEWEL-01)")
    parser.add_argument(
        "--inv-store", default="JEWEL-01",
        help="Store whose inventory quantities populate INVDETAILS (default: JEWEL-01)",
    )
    parser.add_argument(
        "--include-drafts", action="store_true",
        help="Include all active non-blocked SKUs, bypassing sale_ready gate",
    )
    args = parser.parse_args()

    # Import here so --help works without Firebase Admin or a GCP cred file.
    from app.services.nec_jewel_export import (
        BRAND_NAME,
        DEFAULT_TENANT_CODE,
        PROMO_TIERS,
        build_workbook,
        fetch_sellable_skus_from_firestore,
        make_tenant_catg_tree,
    )

    def _repo_path(p: str) -> Path:
        path = Path(p)
        return path.resolve() if path.is_absolute() else (REPO_ROOT / p).resolve()

    output_path = _repo_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    brand = args.brand or BRAND_NAME
    excluded: list[dict[str, Any]] = []

    tenant_code = DEFAULT_TENANT_CODE

    if args.from_json:
        input_path = _repo_path(args.input)
        products = load_from_json(input_path, args.location, sale_ready_only=not args.include_drafts)
        print(f"  [JSON mode] {len(products)} products for export")
    else:
        from app.firestore import db as fs_db
        print("Connecting to Firestore...")
        print(f"  Brand  : {brand}")
        if args.store:
            print(f"  Store  : {args.store}")
        mode_label = "DRAFT (bypassing sale_ready)" if args.include_drafts else "PRODUCTION (sale_ready=true required)"
        print(f"  Mode   : {mode_label}")
        print(f"  InvStore: {args.inv_store}  (inventory quantities for INVDETAILS)")

        tenant_store_code = args.store or args.inv_store
        store_snap = next(
            iter(fs_db.collection("stores").where("store_code", "==", tenant_store_code).limit(1).stream()),
            None,
        )
        if store_snap is not None:
            store_doc = store_snap.to_dict() or {}
            doc_tenant = (store_doc.get("tenant_code") or "").strip()
            if doc_tenant:
                tenant_code = doc_tenant
                print(f"  Tenant : {tenant_code}  (from store {tenant_store_code})")
            else:
                print(f"  Tenant : {tenant_code}  (default; {tenant_store_code} has no tenant_code)")
        else:
            print(f"  Tenant : {tenant_code}  (default; store {tenant_store_code} not found)")

        products, excluded = fetch_sellable_skus_from_firestore(
            fs_db,
            brand_name=brand,
            store_code=args.store,
            inv_store_code=args.inv_store,
            include_drafts=args.include_drafts,
        )
        print(f"\n  Sellable SKUs found: {len(products)}")

    if not products:
        print("\n  No sellable products to export.")
        if excluded:
            print_excluded_report(excluded)
        return

    wb, counts = build_workbook(products, tenant_code=tenant_code)
    wb.save(str(output_path))

    print(f"\n{'='*60}")
    print("  JEWEL NEC POS MASTER DATA EXPORT")
    print(f"{'='*60}")
    print(f"  Output    : {output_path}")
    print(f"  Generated : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Source    : {'JSON (legacy)' if args.from_json else 'Firestore (live)'}")
    print("")
    print(f"  CATG sheet       : {len(make_tenant_catg_tree(tenant_code))} category nodes")
    print(f"  SKU v2 sheet     : {counts['sku']} products")
    print(f"  PLU sheet        : {counts['plu']} barcode mappings")
    print(f"  PRICE sheet      : {counts['price']} priced items")
    print(f"  PROMO sheet      : {counts['promo']} rows ({len(PROMO_TIERS)} tiers x {counts['sku']} SKUs)")
    for disc_id, label, _pct in PROMO_TIERS:
        print(f"                       {disc_id:22s} {label}")
    if args.from_json:
        print("  INVDETAILS sheet : (empty \u2014 JSON mode has no per-store inventory)")
    else:
        if counts["inventory"] == 0:
            print(f"  INVDETAILS sheet : 0 rows \u2014 no inventory at {args.inv_store}")
        else:
            print(f"  INVDETAILS sheet : {counts['inventory']} opening-stock rows @ {args.inv_store}")

    if counts["price"] < counts["sku"]:
        print(f"\n  WARNING  {counts['sku'] - counts['price']} products have no PRICE row")

    print_data_gaps(products)
    if excluded:
        print_excluded_report(excluded)

    print(f"\n{'='*60}")
    print("  Ready to send to Jewel NEC POS team for import.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
