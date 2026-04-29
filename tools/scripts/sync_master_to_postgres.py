#!/usr/bin/env python3
"""
Sync NEW master_product_list.json rows into Postgres.

Creates ``skus`` + ``plus`` + ``inventories`` rows for every master product
whose ``sku_code`` AND ``internal_code`` are both missing from Postgres.
This is the minimum needed for the Data Quality UI's /prices/bulk endpoint
to find the new rows when the user saves a retail price.

By default, scopes to a specific supplier (``--supplier hengweicraft``)
to keep the blast radius small. Use ``--all-missing`` to sync every
master row that has no Postgres counterpart.

Usage:
  python sync_master_to_postgres.py --supplier hengweicraft
  python sync_master_to_postgres.py --supplier hengweicraft --apply
  python sync_master_to_postgres.py --all-missing --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from identifier_utils import validate_identifier_pair
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
MASTER_PATH = REPO_ROOT / "data" / "master_product_list.json"
SUPPLIERS_DIR = REPO_ROOT / "docs" / "suppliers"

DEFAULT_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://retailsg:RetailSG2026Secure@127.0.0.1:5434/retailsg",
)

DEFAULT_BRAND = "VICTORIA ENSO"
DEFAULT_STORE = "JEWEL-01"            # home store for new SKU rows
DEFAULT_INV_STORE = "BREEZE-01"       # where the opening stock currently sits


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_master_products() -> list[dict[str, Any]]:
    return json.loads(MASTER_PATH.read_text())["products"]


def load_supplier_codes(supplier: str) -> set[str]:
    orders_dir = SUPPLIERS_DIR / supplier / "orders"
    if not orders_dir.is_dir():
        raise FileNotFoundError(f"No orders dir: {orders_dir}")
    codes: set[str] = set()
    for f in sorted(orders_dir.glob("*.json")):
        for li in json.loads(f.read_text()).get("line_items", []):
            if li.get("supplier_item_code"):
                codes.add(li["supplier_item_code"])
    return codes


async def fetch_pg_state(session: AsyncSession) -> dict[str, set[str]]:
    """Collect existing sku_codes and legacy_codes from Postgres."""
    r = await session.execute(text("SELECT sku_code, legacy_code FROM skus"))
    sku_codes: set[str] = set()
    legacy_codes: set[str] = set()
    for row in r:
        sku_codes.add(row[0])
        if row[1]:
            legacy_codes.add(row[1])
    r = await session.execute(text("SELECT plu_code FROM plus"))
    plus = {row[0] for row in r}
    return {"sku_codes": sku_codes, "legacy_codes": legacy_codes, "plu_codes": plus}


async def fetch_ids(session: AsyncSession, brand: str, store: str, inv_store: str) -> dict[str, str]:
    r = await session.execute(
        text("SELECT id FROM brands WHERE name = :b"), {"b": brand}
    )
    brand_id = r.scalar_one_or_none()
    if not brand_id:
        raise RuntimeError(f"Brand not found: {brand}")
    r = await session.execute(
        text("SELECT id FROM stores WHERE store_code = :s"), {"s": store}
    )
    store_id = r.scalar_one_or_none()
    if not store_id:
        raise RuntimeError(f"Store not found: {store}")
    r = await session.execute(
        text("SELECT id FROM stores WHERE store_code = :s"), {"s": inv_store}
    )
    inv_store_id = r.scalar_one_or_none()
    if not inv_store_id:
        raise RuntimeError(f"Inventory store not found: {inv_store}")
    return {"brand_id": str(brand_id), "store_id": str(store_id), "inv_store_id": str(inv_store_id)}


def filter_candidates(
    products: list[dict[str, Any]],
    pg: dict[str, set[str]],
    supplier_codes: set[str] | None,
) -> list[dict[str, Any]]:
    """Return master rows that need Postgres creation.

    A row is a candidate iff:
    - its sku_code is NOT already in Postgres
    - AND its internal_code does NOT already match a Postgres legacy_code
      (otherwise it's bridgeable via the existing fallback and we leave it)
    Optionally restricted to ``supplier_codes`` by matching internal_code.
    """
    out = []
    for p in products:
        sku = p.get("sku_code")
        if not sku:
            continue
        if sku in pg["sku_codes"]:
            continue
        ic = p.get("internal_code")
        if ic and ic in pg["legacy_codes"]:
            # Already bridgeable — skip. /prices/bulk will find it via legacy_code.
            continue
        if supplier_codes is not None and ic not in supplier_codes:
            continue
        out.append(p)
    return out


def resolve_product_type_enum(product: dict[str, Any]) -> str:
    """skus.product_type is an enum: 'finished' | 'material' | 'manufactured'.

    The free-text category (Sculpture, Bookend, etc.) lives in ``form_factor``.
    """
    it = product.get("inventory_type") or product.get("product_type")
    if it in {"purchased", "finished"}:
        return "finished"
    if it in {"material"}:
        return "material"
    if it in {"manufactured"}:
        return "manufactured"
    return "finished"


def build_sku_insert_params(
    product: dict[str, Any],
    brand_id: str,
    store_id: str,
) -> dict[str, Any]:
    sku_id = str(uuid.uuid4())
    now = datetime.utcnow()
    return {
        "id": sku_id,
        "sku_code": product["sku_code"][:32],
        "description": (product.get("description") or "")[:60],
        "long_description": product.get("long_description"),
        "cost_price": product.get("cost_price"),
        "brand_id": brand_id,
        "store_id": store_id,
        "tax_code": "G",
        "gender": product.get("gender"),
        "age_group": product.get("age_group"),
        "is_unique_piece": False,
        "use_stock": bool(product.get("use_stock", True)),
        "block_sales": bool(product.get("block_sales", False)),
        "product_type": resolve_product_type_enum(product),
        "form_factor": product.get("product_type"),  # e.g. "Sculpture"
        "attributes": json.dumps({"materials": product.get("material")}) if product.get("material") else None,
        "status": "active",
        "sale_ready": bool(product.get("sale_ready", False)),
        "stocking_status": product.get("stocking_status"),
        "primary_stocking_location": product.get("stocking_location"),
        "legacy_code": product.get("internal_code"),
        "created_at": now,
        "updated_at": now,
    }


SKU_INSERT_SQL = text("""
INSERT INTO skus (
    id, sku_code, description, long_description, cost_price,
    brand_id, store_id, tax_code, gender, age_group,
    is_unique_piece, use_stock, block_sales,
    product_type, form_factor, attributes,
    status, sale_ready, stocking_status, primary_stocking_location,
    legacy_code, created_at, updated_at
) VALUES (
    :id, :sku_code, :description, :long_description, :cost_price,
    :brand_id, :store_id, :tax_code, :gender, :age_group,
    :is_unique_piece, :use_stock, :block_sales,
    CAST(:product_type AS product_type_enum), :form_factor, CAST(:attributes AS jsonb),
    :status, :sale_ready, :stocking_status, :primary_stocking_location,
    :legacy_code, :created_at, :updated_at
)
""")

PLU_INSERT_SQL = text("""
INSERT INTO plus (id, plu_code, sku_id, created_at)
VALUES (:id, :plu_code, :sku_id, :created_at)
""")

INV_INSERT_SQL = text("""
INSERT INTO inventories (
    id, location_status, sku_id, store_id,
    qty_on_hand, reorder_level, reorder_qty, last_updated,
    inventory_type, sourcing_strategy, created_at, updated_at
) VALUES (
    :id, 'STORE', :sku_id, :store_id,
    :qty_on_hand, 0, 0, :last_updated,
    CAST(:inventory_type AS inventory_type_enum),
    CAST(:sourcing_strategy AS sourcing_strategy_enum),
    :created_at, :updated_at
)
ON CONFLICT (store_id, sku_id) DO NOTHING
""")


async def insert_one(
    session: AsyncSession,
    product: dict[str, Any],
    brand_id: str,
    store_id: str,
    inv_store_id: str,
) -> None:
    sku_params = build_sku_insert_params(product, brand_id, store_id)
    validate_identifier_pair(sku_params["sku_code"], product.get("nec_plu"))
    await session.execute(SKU_INSERT_SQL, sku_params)

    plu_code = str(product.get("nec_plu") or "").strip()
    if plu_code:
        await session.execute(PLU_INSERT_SQL, {
            "id": str(uuid.uuid4()),
            "plu_code": plu_code[:20],
            "sku_id": sku_params["id"],
            "created_at": sku_params["created_at"],
        })

    qty = int(product.get("qty_on_hand") or 0)
    if qty > 0:
        await session.execute(INV_INSERT_SQL, {
            "id": str(uuid.uuid4()),
            "sku_id": sku_params["id"],
            "store_id": inv_store_id,
            "qty_on_hand": qty,
            "last_updated": sku_params["created_at"],
            "inventory_type": "purchased",
            "sourcing_strategy": "supplier_premade",
            "created_at": sku_params["created_at"],
            "updated_at": sku_params["created_at"],
        })


# ── CLI ──────────────────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> None:
    products = load_master_products()
    supplier_codes = None
    if args.supplier:
        supplier_codes = load_supplier_codes(args.supplier)
        print(f"Supplier '{args.supplier}': {len(supplier_codes)} item codes")

    eng = create_async_engine(args.db_url, echo=False)
    Session = async_sessionmaker(eng, expire_on_commit=False)
    async with Session() as session:
        pg = await fetch_pg_state(session)
        ids = await fetch_ids(session, args.brand, args.store, args.inv_store)

        candidates = filter_candidates(products, pg, supplier_codes)
        print(f"Master products         : {len(products)}")
        print(f"Postgres SKUs (existing): {len(pg['sku_codes'])}")
        print(f"Candidates to insert    : {len(candidates)}")
        print(f"Target brand            : {args.brand}  ({ids['brand_id'][:8]}\u2026)")
        print(f"Target home store       : {args.store}  ({ids['store_id'][:8]}\u2026)")
        print(f"Target inventory store  : {args.inv_store}  ({ids['inv_store_id'][:8]}\u2026)")
        print()

        if not candidates:
            print("Nothing to sync.")
            await eng.dispose()
            return

        print(f"{'sku_code':18s}  {'plu':14s}  {'internal':10s}  {'type':18s}  {'qty':>4}  desc")
        print("-" * 100)
        for p in candidates:
            print(
                f"{(p.get('sku_code') or ''):18s}  "
                f"{str(p.get('nec_plu') or '')[:14]:14s}  "
                f"{(p.get('internal_code') or '')[:10]:10s}  "
                f"{(p.get('product_type') or '')[:18]:18s}  "
                f"{int(p.get('qty_on_hand') or 0):4d}  "
                f"{(p.get('description') or '')[:40]}"
            )

        if not args.apply:
            print("\n(dry run \u2014 no rows written. Re-run with --apply to persist.)")
            await eng.dispose()
            return

        inserted = 0
        for p in candidates:
            await insert_one(session, p, ids["brand_id"], ids["store_id"], ids["inv_store_id"])
            inserted += 1
        await session.commit()
        print(f"\nInserted {inserted} sku rows (+ plu and inventory where applicable).")

    await eng.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--supplier", default=None, help="Limit to a supplier's item codes")
    parser.add_argument("--all-missing", action="store_true", help="Sync every master row missing from Postgres")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry-run)")
    parser.add_argument("--brand", default=DEFAULT_BRAND)
    parser.add_argument("--store", default=DEFAULT_STORE, help="Home store for new SKU rows")
    parser.add_argument("--inv-store", default=DEFAULT_INV_STORE, help="Store where opening inventory is booked")
    parser.add_argument("--db-url", default=DEFAULT_DATABASE_URL)
    args = parser.parse_args()

    if not args.supplier and not args.all_missing:
        print("Pick one of --supplier <name> or --all-missing")
        sys.exit(2)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
