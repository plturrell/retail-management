#!/usr/bin/env python3
"""
Sync master_product_list.json rows into Firestore so the POS barcode
endpoint (`GET /api/barcode/{plu_code}`) can resolve them.

Writes the three documents the live FastAPI router reads:

    skus/{sku_id}                             (top-level, looked up by id)
    plus/{plu_id}        plu_code, sku_id     (top-level, queried by plu_code)
    prices/{price_id}    sku_id, store_id,    (top-level, only when --with-prices)
                         price_incl_tax, ...

Idempotent: if a `plus` doc already exists for a PLU, the linked SKU is
updated in place; otherwise new docs are created.

Usage:
  # Dry-run (default) — see what would change
  python tools/scripts/sync_master_to_firestore.py --only-plus 2000000000718,2000000005027

  # Push the 5 P-touch test labels with placeholder prices
  python tools/scripts/sync_master_to_firestore.py \\
      --only-plus 2000000000718,2000000005027,2000000005034,2000000005041,2000000005058 \\
      --with-prices --bootstrap-store --apply

  # Sync every homeware item that has a valid nec_plu
  python tools/scripts/sync_master_to_firestore.py --homeware-only --apply
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "scripts"))

from app.firestore_helpers import (  # noqa: E402
    create_document,
    get_document,
    query_collection,
    update_document,
)
from identifier_utils import is_valid_ean13  # noqa: E402

MASTER_PATH = REPO_ROOT / "data" / "master_product_list.json"

DEFAULT_STORE_CODE = "JEWEL-01"
DEFAULT_BRAND = "VICTORIA ENSO"

# Canonical store seeds (mirrors tools/scripts/seed_stores.py STORES).
# Used by --bootstrap-store when a store_code does not yet exist in Firestore.
STORE_SEEDS: dict[str, dict[str, Any]] = {
    "TAKA-01": {
        "store_code": "TAKA-01",
        "name": "VictoriaEnso – Takashimaya",
        "location": "Takashimaya Shopping Centre",
        "address": "391 Orchard Rd, #B1-13, Singapore 238872",
        "is_active": True,
    },
    "ISETAN-01": {
        "store_code": "ISETAN-01",
        "name": "VictoriaEnso – Isetan Scotts",
        "location": "Isetan Scotts",
        "address": "350 Orchard Road, Shaw House, Singapore 238868",
        "is_active": True,
    },
    "JEWEL-01": {
        "store_code": "JEWEL-01",
        "name": "VictoriaEnso – Jewel Changi",
        "location": "Jewel Changi Airport",
        "address": "78 Airport Blvd, #B2-208, Singapore 819666",
        "is_active": True,
    },
    "BREEZE-01": {
        "store_code": "BREEZE-01",
        "name": "VictoriaEnso – Breeze by East (HQ & Warehouse)",
        "location": "Breeze by East",
        "address": "Singapore",
        "is_active": False,
    },
    "ONLINE-01": {
        "store_code": "ONLINE-01",
        "name": "VictoriaEnso – Online",
        "location": "Online",
        "address": "https://victoriaenso.com",
        "is_active": True,
    },
}


# ── Source filtering ─────────────────────────────────────────────────────────

def load_master_products() -> list[dict[str, Any]]:
    return json.loads(MASTER_PATH.read_text())["products"]


def is_homeware(p: dict[str, Any]) -> bool:
    return (
        "home" in str(p.get("google_product_category", "")).lower()
        or "decor" in str(p.get("category", "")).lower()
    )


def select_products(
    products: list[dict[str, Any]],
    *,
    only_plus: set[str] | None,
    homeware_only: bool,
) -> list[dict[str, Any]]:
    out = []
    for p in products:
        plu = str(p.get("nec_plu") or "").strip()
        sku = str(p.get("sku_code") or "").strip()
        if not plu or not sku:
            continue
        if not is_valid_ean13(plu):
            continue
        if only_plus is not None and plu not in only_plus:
            continue
        if homeware_only and not is_homeware(p):
            continue
        out.append(p)
    return out


# ── Firestore lookups ────────────────────────────────────────────────────────

def find_store_id(store_code: str) -> str | None:
    matches = query_collection("stores", filters=[("store_code", "==", store_code)], limit=1)
    return str(matches[0]["id"]) if matches else None


def bootstrap_store(store_code: str, *, apply: bool) -> str:
    """Upsert the canonical store doc for ``store_code`` and return its id.

    Mirrors the schema in ``tools/scripts/seed_stores.py``. Idempotent: if a
    doc with this store_code already exists, returns its id without writing.
    """
    seed = STORE_SEEDS.get(store_code)
    if seed is None:
        raise RuntimeError(
            f"No canonical seed for store_code={store_code!r}. "
            f"Known: {sorted(STORE_SEEDS)}. Add it to STORE_SEEDS or seed manually."
        )
    existing = find_store_id(store_code)
    if existing:
        return existing
    new_id = str(uuid.uuid4())
    if apply:
        now = datetime.now(timezone.utc)
        create_document(
            "stores",
            {"id": new_id, "created_at": now, "updated_at": now, **seed},
            doc_id=new_id,
        )
    return new_id


def find_brand_id(brand_name: str) -> str | None:
    matches = query_collection("brands", filters=[("name", "==", brand_name)], limit=1)
    return str(matches[0]["id"]) if matches else None


def find_sku_id_by_code(sku_code: str) -> str | None:
    matches = query_collection("skus", filters=[("sku_code", "==", sku_code)], limit=1)
    return str(matches[0]["id"]) if matches else None


def find_plu_doc(plu_code: str) -> dict[str, Any] | None:
    matches = query_collection("plus", filters=[("plu_code", "==", plu_code)], limit=1)
    return matches[0] if matches else None


# ── Doc builders ─────────────────────────────────────────────────────────────

def build_sku_doc(p: dict[str, Any], *, sku_id: str, store_id: str, brand_id: str | None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "id": sku_id,
        "sku_code": p["sku_code"][:32],
        "description": (p.get("description") or "")[:60],
        "long_description": p.get("long_description"),
        "cost_price": float(p["cost_price"]) if p.get("cost_price") is not None else None,
        "store_id": store_id,
        "brand_id": brand_id,
        "category_id": None,
        "tax_code": "G",
        "gender": p.get("gender"),
        "age_group": p.get("age_group"),
        "is_unique_piece": False,
        "use_stock": bool(p.get("use_stock", True)),
        "block_sales": bool(p.get("block_sales", False)),
        "internal_code": p.get("internal_code"),
        "amazon_sku": p.get("amazon_sku"),
        "google_product_id": p.get("google_product_id"),
        "nec_plu": p.get("nec_plu"),
        "material": p.get("material"),
        "product_type": p.get("product_type"),
        "source": "master_product_list",
        "created_at": now,
        "updated_at": now,
    }



def placeholder_retail(cost: float | None) -> float | None:
    """cost x 3, rounded down to .99 — placeholder for POS scan testing only."""
    if cost is None:
        return None
    raw = float(cost) * 3.0
    return float(int(raw) - 1) + 0.99 if raw >= 2 else 1.99


def build_price_doc(p: dict[str, Any], *, sku_id: str, store_id: str) -> dict[str, Any] | None:
    retail = p.get("retail_price")
    if retail is None:
        retail = placeholder_retail(p.get("cost_price"))
    if retail is None:
        return None
    now = datetime.now(timezone.utc)
    today = date.today()
    return {
        "id": str(uuid.uuid4()),
        "sku_id": sku_id,
        "store_id": store_id,
        "price_incl_tax": float(retail),
        "price_excl_tax": round(float(retail) / 1.09, 2),  # SG GST 9%
        "price_unit": 1,
        "valid_from": today.isoformat(),
        "valid_to": date(today.year + 5, 12, 31).isoformat(),
        "source": "master_sync_placeholder" if p.get("retail_price") is None else "master_sync",
        "created_at": now,
        "updated_at": now,
    }


# ── Sync ─────────────────────────────────────────────────────────────────────

def sync_one(
    p: dict[str, Any],
    *,
    store_id: str,
    brand_id: str | None,
    with_prices: bool,
    apply: bool,
) -> dict[str, str]:
    """Returns a result dict: {action: created|updated, sku_id, plu_id, ...}."""
    plu_code = str(p["nec_plu"]).strip()
    sku_code = str(p["sku_code"]).strip()

    existing_plu = find_plu_doc(plu_code)
    if existing_plu:
        sku_id = str(existing_plu.get("sku_id") or "")
        plu_id = str(existing_plu["id"])
        action = "updated"
    else:
        # PLU doesn't exist; reuse SKU if its sku_code is already in Firestore.
        sku_id = find_sku_id_by_code(sku_code) or str(uuid.uuid4())
        plu_id = str(uuid.uuid4())
        action = "created"

    sku_doc = build_sku_doc(p, sku_id=sku_id, store_id=store_id, brand_id=brand_id)
    price_doc = build_price_doc(p, sku_id=sku_id, store_id=store_id) if with_prices else None

    if apply:
        existing_sku = get_document("skus", sku_id)
        if existing_sku:
            # Preserve created_at on update
            sku_doc["created_at"] = existing_sku.get("created_at", sku_doc["created_at"])
            update_document("skus", sku_id, sku_doc)
        else:
            create_document("skus", sku_doc, doc_id=sku_id)

        if existing_plu:
            update_document("plus", plu_id, {"plu_code": plu_code, "sku_id": sku_id})
        else:
            create_document("plus", {"id": plu_id, "plu_code": plu_code, "sku_id": sku_id}, doc_id=plu_id)

        if price_doc:
            create_document("prices", price_doc, doc_id=price_doc["id"])

    return {
        "action": action,
        "sku_code": sku_code,
        "plu_code": plu_code,
        "sku_id": sku_id,
        "plu_id": plu_id,
        "wrote_price": "yes" if price_doc else "no",
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--only-plus",
        default=None,
        help="Comma-separated list of PLU codes to sync (default: all matching products).",
    )
    parser.add_argument(
        "--homeware-only",
        action="store_true",
        help="Restrict to products in 'Home Decor' / 'Home & Garden > Decor' categories.",
    )
    parser.add_argument(
        "--store-code",
        default=DEFAULT_STORE_CODE,
        help=f"Firestore store_code to attach SKUs to (default: {DEFAULT_STORE_CODE}).",
    )
    parser.add_argument(
        "--with-prices",
        action="store_true",
        help="Also write a top-level prices/{id} doc so the barcode lookup returns current_price.",
    )
    parser.add_argument(
        "--bootstrap-store",
        action="store_true",
        help="Create the --store-code store doc in Firestore if missing (uses canonical seed from seed_stores.py).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to Firestore (default is dry-run).",
    )
    args = parser.parse_args()

    only_plus = (
        {p.strip() for p in args.only_plus.split(",") if p.strip()}
        if args.only_plus
        else None
    )

    products = load_master_products()
    targets = select_products(products, only_plus=only_plus, homeware_only=args.homeware_only)

    print(f"Master products            : {len(products)}")
    print(f"Selected for sync          : {len(targets)}")
    if only_plus:
        missing = only_plus - {p["nec_plu"] for p in targets}
        if missing:
            print(f"  WARNING: PLUs not found in master list: {sorted(missing)}")
    if not targets:
        print("Nothing to do.")
        return

    print(f"Target store_code          : {args.store_code}")
    store_id = find_store_id(args.store_code)
    if store_id is None:
        if args.bootstrap_store:
            store_id = bootstrap_store(args.store_code, apply=args.apply)
            tag = "created" if args.apply else "would-create"
            print(f"  store_id  = {store_id}  [{tag}]")
        else:
            raise RuntimeError(
                f"Store {args.store_code!r} not in Firestore. "
                f"Re-run with --bootstrap-store to create it from the canonical seed."
            )
    else:
        print(f"  store_id  = {store_id}  [existing]")
    brand_id = find_brand_id(DEFAULT_BRAND)
    print(f"  brand_id  = {brand_id or '(not found, leaving null)'}")
    print(f"With prices                : {args.with_prices}")
    print(f"Mode                       : {'APPLY' if args.apply else 'dry-run'}")
    print()

    print(f"{'plu_code':14s}  {'sku_code':18s}  {'action':8s}  {'price':5s}  description")
    print("-" * 100)
    for p in targets:
        result = sync_one(
            p,
            store_id=store_id,
            brand_id=brand_id,
            with_prices=args.with_prices,
            apply=args.apply,
        )
        print(
            f"{result['plu_code']:14s}  {result['sku_code']:18s}  "
            f"{result['action']:8s}  {result['wrote_price']:5s}  "
            f"{(p.get('description') or '')[:50]}"
        )

    if not args.apply:
        print("\n(dry-run — no Firestore writes. Re-run with --apply to persist.)")
    else:
        print(f"\nSynced {len(targets)} PLU(s) to Firestore.")


if __name__ == "__main__":
    main()
