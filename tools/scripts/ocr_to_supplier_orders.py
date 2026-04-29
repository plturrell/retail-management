#!/usr/bin/env python3
"""
OCR → Supplier Orders Converter + TiDB Ingest

Transforms JSON output from supplier_ocr_pipeline.py into the structured
order format expected by ingest_supplier_orders.py, then optionally:
  1. Writes order JSON files to docs/suppliers/<supplier>/orders/
  2. Runs ingest_supplier_orders.py --apply to create new SKUs in master list
  3. Writes stock movements to TiDB via inventory_ledger.record_movement()

Usage:
  # Dry run — preview what would be ingested
  python ocr_to_supplier_orders.py \\
    --ocr-file data/ocr_outputs/supplier_docs/_combined_supplier_extract.json \\
    --supplier china_suppliers

  # Apply — write order files + ingest to master list
  python ocr_to_supplier_orders.py \\
    --ocr-file data/ocr_outputs/supplier_docs/_combined_supplier_extract.json \\
    --supplier china_suppliers \\
    --apply

  # Also write stock movements to TiDB
  python ocr_to_supplier_orders.py \\
    --ocr-file data/ocr_outputs/supplier_docs/_combined_supplier_extract.json \\
    --supplier china_suppliers \\
    --apply --tidb --store-id <STORE_UUID>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SUPPLIERS_DIR = REPO_ROOT / "docs" / "suppliers"

# ── Gemstone material → 4-char code (for VE SKU generation) ─────────────────
GEMSTONE_MATERIAL_CODE: dict[str, str] = {
    "amethyst":    "AMET",
    "citrine":     "CITR",
    "sapphire":    "SAPH",
    "topaz":       "TOPA",
    "jade":        "JADE",
    "tourmaline":  "TOUR",
    "aquamarine":  "AQUA",
    "ruby":        "RUBY",
    "garnet":      "GRNT",
    "moonstone":   "MOON",
    "rose quartz": "RQTZ",
    "kunzite":     "KUNZ",
    "peridot":     "PERI",
    "crystal":     "CRYS",
    "gemstone":    "GEMS",
    "quartz":      "QRTZ",
}

# ── Product type → 3-char code (must align with ingest_supplier_orders.py) ──
JEWELLERY_PRODUCT_TYPE_CODE: dict[str, str] = {
    "Bracelet":        "BRC",
    "Necklace":        "NCK",
    "Ring":            "RNG",
    "Pendant":         "PND",
    "Earring":         "ERR",
    "Charm":           "CHM",
    "Loose Gemstone":  "GMS",
    "Tumbled Stone":   "TUM",
    "Crystal Cluster": "CLU",
    "Gemstone Bead":   "BED",
    "Cabochon":        "CAB",
    "Bead Strand":     "STR",
    "Gift Set":        "GST",
    "Accessory":       "ACC",
    "Figurine":        "FIG",
    "Sculpture":       "SCU",
    "Crystal Point":   "CPT",
    "Healing Crystal": "HCR",
}

# Default CNY → SGD exchange rate (update periodically)
DEFAULT_CNY_TO_SGD = 1 / 5.34  # ~0.187 SGD per CNY


def resolve_material_code(material: str | None) -> str:
    """Return 4-char material code from a gemstone name."""
    if not material:
        return "GEMS"
    lower = material.lower().strip()
    for key, code in GEMSTONE_MATERIAL_CODE.items():
        if key in lower:
            return code
    return "GEMS"


def normalise_supplier_name(raw: str | None, fallback: str) -> str:
    return (raw or fallback).strip() or fallback


def ocr_doc_to_order(doc: dict[str, Any], supplier_folder: str) -> dict[str, Any] | None:
    """Convert a single OCR document dict → ingest_supplier_orders order format."""
    items = doc.get("items") or []
    if not items:
        return None

    supplier_name = normalise_supplier_name(
        doc.get("supplier_name"), supplier_folder.replace("_", " ").title()
    )
    currency = doc.get("currency") or "CNY"
    doc_date = doc.get("document_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    doc_number = doc.get("document_number") or doc.get("source_file", "unknown")

    line_items: list[dict[str, Any]] = []
    for item in items:
        supplier_code = item.get("supplier_item_code")
        if not supplier_code:
            # Generate a synthetic code from product type + sequence
            pt = (item.get("product_type") or "ITEM").replace(" ", "")[:4].upper()
            supplier_code = f"{pt}-{str(uuid.uuid4())[:6].upper()}"

        line_items.append({
            "supplier_item_code": supplier_code,
            "display_name": item.get("product_name_en") or item.get("product_name_cn") or "Unknown Item",
            "product_name_cn": item.get("product_name_cn"),
            "material_description": item.get("material") or "",
            "product_type": item.get("product_type") or "Accessory",
            "colour": item.get("colour"),
            "size": item.get("size"),
            "quantity": int(item.get("quantity") or 0),
            "unit_cost_cny": float(item.get("unit_price") or 0),
            "unit_cost": float(item.get("unit_price") or 0),
            "total_cost_cny": float(item.get("total_price") or 0),
            "note": item.get("notes"),
        })

    # Build order record matching ingest_supplier_orders.py expectations
    order = {
        "supplier_name": supplier_name,
        "order_reference": doc_number,
        "order_date": doc_date,
        "currency": currency,
        "document_total": doc.get("document_total"),
        "source_file": doc.get("source_file"),
        "lineage_id": doc.get("lineage_id"),
        "payment_breakdown": [
            {
                "currency": currency,
                "reported_fx_rate_cny_per_sgd": 5.34 if currency == "CNY" else None,
            }
        ],
        "inventory_movement": {
            "current_location": "warehouse",
            "destination": "shop_floor",
        },
        "line_items": line_items,
        "notes": doc.get("notes"),
    }
    return order


def write_order_files(
    orders: list[dict[str, Any]],
    supplier_dir: Path,
    dry_run: bool,
) -> list[Path]:
    """Write each order as a JSON file under docs/suppliers/<name>/orders/."""
    orders_dir = supplier_dir / "orders"
    written: list[Path] = []

    for order in orders:
        ref = (order.get("order_reference") or "unknown").replace(" ", "_").replace("/", "-")
        date = (order.get("order_date") or "undated").replace("-", "")
        fname = f"ocr_{date}_{ref}.json"
        out_path = orders_dir / fname

        print(f"  {'[DRY RUN] Would write' if dry_run else 'Writing'}: {out_path.relative_to(REPO_ROOT)}")
        print(f"    → {len(order['line_items'])} line items  |  "
              f"supplier: {order['supplier_name']}  |  "
              f"ref: {order.get('order_reference')}")

        if not dry_run:
            orders_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(order, indent=2, ensure_ascii=False))
            written.append(out_path)

    return written


async def write_tidb_movements(
    orders: list[dict[str, Any]],
    store_id: str,
) -> None:
    """Write incoming stock movements to TiDB via inventory_ledger."""
    # Add backend to path
    backend_path = REPO_ROOT / "backend"
    sys.path.insert(0, str(backend_path))

    try:
        from app.db import tidb
        from app.services.inventory_ledger import record_movement

        if not tidb.is_enabled():
            print("  WARNING: TIDB_DATABASE_URL not set — skipping TiDB write.")
            return

        total_written = 0
        for order in orders:
            for item in order.get("line_items", []):
                qty = int(item.get("quantity") or 0)
                if qty <= 0:
                    continue

                supplier_code = item.get("supplier_item_code", "UNKNOWN")
                # Use supplier code as a synthetic SKU id until matched to master
                synthetic_sku_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, supplier_code))

                row_id = await record_movement(
                    store_id=store_id,
                    sku_id=synthetic_sku_id,
                    delta_qty=qty,
                    source="supplier_ocr",
                    inventory_type="finished",
                    resulting_qty=qty,
                    reference_type="supplier_order",
                    reference_id=order.get("order_reference"),
                    reason=f"OCR ingest from {order.get('source_file', 'unknown')}",
                )
                if row_id:
                    total_written += 1
                    print(f"    TiDB ✓ {supplier_code}  qty={qty}  row={row_id}")

        print(f"  TiDB: {total_written} stock movements written.")
    except ImportError as e:
        print(f"  WARNING: Could not import backend modules: {e}")
        print("  Make sure TIDB_DATABASE_URL is set in your environment.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--ocr-file",
        default="data/ocr_outputs/supplier_docs/_combined_supplier_extract.json",
        help="Path to the combined OCR output JSON",
    )
    parser.add_argument(
        "--supplier",
        default="china_suppliers",
        help="Supplier folder name under docs/suppliers/",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write order files and run ingest. Default is dry-run.",
    )
    parser.add_argument(
        "--tidb",
        action="store_true",
        help="Also write incoming stock movements to TiDB",
    )
    parser.add_argument(
        "--store-id",
        default="",
        help="Store UUID for TiDB stock movements (required with --tidb)",
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Write order files but skip running ingest_supplier_orders.py",
    )
    args = parser.parse_args()

    # ── Load OCR output ───────────────────────────────────────────────────────
    ocr_file = REPO_ROOT / args.ocr_file if not Path(args.ocr_file).is_absolute() else Path(args.ocr_file)
    if not ocr_file.exists():
        print(f"ERROR: OCR file not found: {ocr_file}", file=sys.stderr)
        sys.exit(1)

    combined = json.loads(ocr_file.read_text())
    documents = combined.get("documents", [])
    print(f"\nOCR → Supplier Orders Converter")
    print(f"{'=' * 60}")
    print(f"  OCR file    : {ocr_file.relative_to(REPO_ROOT)}")
    print(f"  Supplier    : {args.supplier}")
    print(f"  Documents   : {len(documents)}")
    print(f"  Mode        : {'APPLY' if args.apply else 'DRY RUN'}")
    print()

    # ── Convert ───────────────────────────────────────────────────────────────
    orders: list[dict[str, Any]] = []
    skipped = 0
    for doc in documents:
        order = ocr_doc_to_order(doc, args.supplier)
        if order:
            orders.append(order)
        else:
            skipped += 1
            print(f"  SKIP (no items): {doc.get('source_file', '?')}")

    print(f"\n  Converted: {len(orders)} orders  |  Skipped: {skipped} empty docs")
    total_lines = sum(len(o["line_items"]) for o in orders)
    total_qty = sum(
        li.get("quantity", 0)
        for o in orders
        for li in o["line_items"]
    )
    print(f"  Total line items: {total_lines}  |  Total units: {total_qty}")
    print()

    # ── Print preview ─────────────────────────────────────────────────────────
    print(f"  {'Order Ref':20s}  {'Supplier':30s}  {'Lines':>5}  {'Currency'}")
    print(f"  {'-'*80}")
    for order in orders:
        print(f"  {order.get('order_reference', '?'):20s}  "
              f"{order.get('supplier_name', '?'):30s}  "
              f"{len(order['line_items']):>5}  "
              f"{order.get('currency', 'CNY')}")

    # ── Write order files ─────────────────────────────────────────────────────
    supplier_dir = SUPPLIERS_DIR / args.supplier
    print()
    written = write_order_files(orders, supplier_dir, dry_run=not args.apply)

    # ── Run ingest_supplier_orders.py ─────────────────────────────────────────
    if args.apply and written and not args.skip_ingest:
        print(f"\n  Running ingest_supplier_orders.py --apply ...")
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "ingest_supplier_orders.py"),
             "--supplier", args.supplier, "--apply"],
            cwd=str(Path(__file__).parent),
            capture_output=False,
        )
        if result.returncode != 0:
            print(f"  WARNING: ingest returned exit code {result.returncode}")

    # ── Write TiDB stock movements ────────────────────────────────────────────
    if args.tidb and args.apply:
        if not args.store_id:
            print("  ERROR: --store-id required when using --tidb", file=sys.stderr)
        else:
            import asyncio
            print(f"\n  Writing stock movements to TiDB (store={args.store_id})...")
            asyncio.run(write_tidb_movements(orders, args.store_id))

    if not args.apply:
        print(f"\n  (Dry run complete — re-run with --apply to persist)")


if __name__ == "__main__":
    main()
