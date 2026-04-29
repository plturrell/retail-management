#!/usr/bin/env python3
"""Reclassify mislabeled rows in master_product_list.json.

Two distinct corrections, applied per explicit SKU allowlist:

1. Decorative homeware currently marked inventory_type=finished is really
   bought-in finished goods (imported decor). Change inventory_type to
   `purchased`; sourcing_strategy stays `supplier_premade`.

2. Generic charms / restring services / generic-XXXX jewelry items currently
   marked sourcing_strategy=supplier_premade are actually in-house assembly
   work. Change sourcing_strategy to `manufactured_standard`; inventory_type
   stays `finished`.

`material` rows (loose beads) and the two already-correct `manufactured_standard`
rows are left untouched.

Usage:
    python tools/scripts/reclassify_master_taxonomy.py            # dry-run, prints diff
    python tools/scripts/reclassify_master_taxonomy.py --write    # apply
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MASTER = REPO_ROOT / "data" / "master_product_list.json"

# Decorative homeware: finished -> purchased (sourcing untouched)
DECORATIVE_SKUS: set[str] = {
    "VEBWLAMET0000062",  # Bowl made of Silver and Amethyst
    "VEBKECRYS0000067",  # bookend made of crystal
    "VEBKECRYS0000068",  # bookend made of crystal
    "VEBKECRYS0000069",  # bookend made of crystal
    "VEBKECRYS0000066",  # bookend made of marble and crystal
    "VEBKECRYS0000075",  # bookend made of marble and crystal
    "VECLUCRYS0000072",  # crystal cluster
    "VECPTCRYS0000079",  # Tower made of Crystal and Metal
    "VEFIGCRYS0000056",  # figurine made of crystal and metal
    "VESCUCRYS0000077",  # Decorative Sculpture
    "VESCUCRYS0000078",  # Sculpture made of Marble and Crystal
    "VESCUCRYS0000076",  # sculpture made of marble and crystal
    "VESCUMALA0000063",  # decorative sculpture, marble + malachite
    "VEBKEMARB0000070",  # bookend made of stone and marble
    "VEDECMARB0000071",  # decorative object made of marble and metal
    "VEFIGMARB0000061",  # figurine made of metal and marble
    "VEBOXROSE0000081",  # Rose Quartz Box RX31
    "VEBKESMOK0000074",  # Bookend made of Acrylic and Smoky Quartz
    "VEBKESTON0000073",  # Bookend made of Acrylic and Stone
    "VEBKESTON0000057",  # bookend made of stone and brass
    "VESCUSTON0000059",  # mountain sculpture made of stone and metal
    "VEWALSTON0000058",  # wall decor made of metal and stone
    "VEWALSTON0000065",  # wall decor made of metal and stone
    "VEBOXXXXX0000025",  # Higonie Gare Box
}

# In-house assembly / restring services: sourcing -> manufactured_standard
MANUFACTURED_SKUS: set[str] = {
    "VEBRAXXXX0000307",  # Bracelet X3 (generic in-house bracelet)
    "VECHMXXXX0000158",  # 26 Charm
    "VECHMXXXX0000202",  # 4 Charm
    "VECHMXXXX0000315",  # Charm
    "VENECXXXX0000320",  # chyse coile necklace
    "VEPENXXXX0000422",  # Pendant - Evenue
    "VERNGXXXX0000120",  # 15. Restring
    "VERNGXXXX0000159",  # 26. Restring
    "VERNGXXXX0000186",  # 30. Restring
    "VERNGXXXX0000432",  # Q. lestring
    "VERNGXXXX0000435",  # Restring (Evenue)
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Apply changes (default: dry-run)")
    args = parser.parse_args()

    data = json.loads(MASTER.read_text())
    products = data.get("products", [])

    deco_changes: list[tuple[str, str, str, str]] = []
    mfg_changes: list[tuple[str, str, str, str]] = []
    missing_deco = set(DECORATIVE_SKUS)
    missing_mfg = set(MANUFACTURED_SKUS)

    for p in products:
        sku = p.get("sku_code") or ""
        if sku in DECORATIVE_SKUS:
            missing_deco.discard(sku)
            old_iv = p.get("inventory_type") or ""
            if old_iv != "purchased":
                deco_changes.append((sku, (p.get("description") or "")[:50], old_iv, "purchased"))
                if args.write:
                    p["inventory_type"] = "purchased"
        if sku in MANUFACTURED_SKUS:
            missing_mfg.discard(sku)
            old_src = p.get("sourcing_strategy") or ""
            if old_src != "manufactured_standard":
                mfg_changes.append((sku, (p.get("description") or "")[:50], old_src, "manufactured_standard"))
                if args.write:
                    p["sourcing_strategy"] = "manufactured_standard"

    print("=" * 90)
    print(f"  RECLASSIFY MASTER TAXONOMY  ({'APPLY' if args.write else 'DRY-RUN'})")
    print("=" * 90)

    print(f"\n[1/2] Decorative: inventory_type finished -> purchased  ({len(deco_changes)} rows)")
    for sku, desc, old, new in deco_changes:
        print(f"    {sku}  {desc:50}  {old} -> {new}")

    print(f"\n[2/2] In-house assembly: sourcing_strategy -> manufactured_standard  ({len(mfg_changes)} rows)")
    for sku, desc, old, new in mfg_changes:
        print(f"    {sku}  {desc:50}  {old} -> {new}")

    if missing_deco:
        print(f"\n[!] Decorative SKUs not found in master ({len(missing_deco)}):")
        for sku in sorted(missing_deco):
            print(f"    {sku}")
    if missing_mfg:
        print(f"\n[!] Manufactured SKUs not found in master ({len(missing_mfg)}):")
        for sku in sorted(missing_mfg):
            print(f"    {sku}")

    if args.write:
        MASTER.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"\n[OK] Wrote {MASTER.relative_to(REPO_ROOT)}")
    else:
        print("\n[DRY-RUN] No file written. Re-run with --write to apply.")


if __name__ == "__main__":
    main()
