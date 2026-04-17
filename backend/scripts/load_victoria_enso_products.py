"""Load VICTORIA ENSO master product list into the database.

Source: ``data/master_product_list.json`` (501 products — jewellery, loose
gemstones, home decor pieces). These are OUR own branded products, not
supplier products.

For each product this script:
  1. Ensures the VICTORIA ENSO brand exists.
  2. Ensures retail stores exist: JEWEL-01 (Jewel Changi), TAKA-01
     (Takashimaya counter), WORKSHOP-01 (atelier / not a POS location).
  3. Upserts the VE category hierarchy rooted at ``VE`` (Jewellery, Home
     Decor, Gifts + leaf subcategories).
  4. Upserts an ``SKU`` with a newly generated internal hierarchical code
     (e.g. JWL-GEM-000001), preserving the legacy VE code in
     ``legacy_code`` (A448 etc.) and the old padded code in ``attributes``.
  5. Writes marketplace identifiers: amazon_sku, google_product_id,
     google_product_category.
  6. Creates a PLU row from ``nec_plu``.
  7. Creates a Price row from ``retail_price`` when present.
  8. Creates Inventory rows in the right store based on ``stocking_location``.
  9. Sets sale_ready / stocking_status / product_type enum correctly.

Idempotent — upserts by legacy_code / sku_code / plu_code.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.inventory import SKU, Category, Brand, Inventory, PLU, Price, ProductType
from app.models.inventory import InventoryLocationState
from app.models.store import Store, StoreTypeEnum
from app.services.sku_codes import generate_code, seed_counters_from_db

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://retailsg:RetailSG2026Secure@127.0.0.1:5434/retailsg",
)
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = Path(os.environ.get(
    "VE_DATA_FILE",
    str(REPO_ROOT / "data" / "master_product_list.json"),
))

BRAND_NAME = "VICTORIA ENSO"
GST_RATE = Decimal("0.09")
FAR_FUTURE = date(2099, 12, 31)


# ------------------------------------------------------------------ #
# VE category tree — parent_code → list[(child_code, description, cag_code)]
# These mirror tools/scripts/export_nec_jewel.py's TENANT_CATG_TREE so the
# NEC workbook will map cleanly.
# ------------------------------------------------------------------ #

VE_ROOT_CODE = "VE"

VE_TREE: list[tuple[str | None, str, str, str]] = [
    # Level 1 — top-level categories under VE root
    (VE_ROOT_CODE, "VE_JEWELLERY", "Jewellery", ""),
    (VE_ROOT_CODE, "VE_HOMEDECOR", "Home Decor", ""),
    (VE_ROOT_CODE, "VE_GIFTS",     "Gifts & Souvenirs", ""),
    # Level 2 — Jewellery
    ("VE_JEWELLERY", "VE_JW_BRACELET",  "Bracelets",          "BANGLE & BRACELETS"),
    ("VE_JEWELLERY", "VE_JW_NECKLACE",  "Necklaces",          "NECKLACE"),
    ("VE_JEWELLERY", "VE_JW_RING",      "Rings",              "RINGS"),
    ("VE_JEWELLERY", "VE_JW_EARRING",   "Earrings",           "EARRINGS"),
    ("VE_JEWELLERY", "VE_JW_CHARM",     "Charms & Pendants",  "CHARMS"),
    ("VE_JEWELLERY", "VE_JW_STONE",     "Precious Stones",    "PRECIOUS STONE/GOLD"),
    ("VE_JEWELLERY", "VE_JW_COSTUME",   "Costume Jewellery",  "COSTUME JEWELLERY"),
    ("VE_JEWELLERY", "VE_JW_ACC",       "Jewellery Accessory", "JEWELLERY ACCESSORY"),
    # Level 2 — Home Decor
    ("VE_HOMEDECOR", "VE_HD_DECOR",     "Decorative Items",   "DECORATIVE ITEM"),
    # Level 2 — Gifts
    ("VE_GIFTS",     "VE_GF_GENERAL",   "General Souvenirs",  "GENERAL SOUVENIRS"),
]

# product_type → leaf category code
PRODUCT_TYPE_TO_CATG: dict[str, str] = {
    # Jewellery
    "Bracelet": "VE_JW_BRACELET",
    "Necklace": "VE_JW_NECKLACE",
    "Ring": "VE_JW_RING",
    "Earring": "VE_JW_EARRING",
    "Charm": "VE_JW_CHARM",
    "Pendant": "VE_JW_CHARM",
    "Bead Strand": "VE_JW_COSTUME",
    "Accessory": "VE_JW_ACC",
    # Precious stones & crystals
    "Loose Gemstone": "VE_JW_STONE",
    "Raw Specimen": "VE_JW_STONE",
    "Crystal Cluster": "VE_JW_STONE",
    "Crystal Point": "VE_JW_STONE",
    "Tumbled Stone": "VE_JW_STONE",
    "Gemstone Bead": "VE_JW_STONE",
    "Healing Crystal": "VE_JW_STONE",
    # Home decor
    "Figurine": "VE_HD_DECOR",
    "Sculpture": "VE_HD_DECOR",
    "Bookend": "VE_HD_DECOR",
    "Bowl": "VE_HD_DECOR",
    "Vase": "VE_HD_DECOR",
    "Box": "VE_HD_DECOR",
    "Tray": "VE_HD_DECOR",
    "Decorative Object": "VE_HD_DECOR",
    "Wall Art": "VE_HD_DECOR",
    # Gifts / services
    "Gift Set": "VE_GF_GENERAL",
    "Repair Service": "VE_GF_GENERAL",
}


# ------------------------------------------------------------------ #
# Store layout — which store_code holds inventory for each stocking_location
# ------------------------------------------------------------------ #

LOCATION_TO_STORE: dict[str, str] = {
    "jewel":                "JEWEL-01",
    "breeze":               "BREEZE-01",
    "takashimaya_counter":  "TAKA-01",
    "workshop":             "WORKSHOP-01",
}

# The single store that owns SKU records (master catalogue).
SKU_MASTER_STORE = "JEWEL-01"

# Stores we must ensure exist for this load
REQUIRED_STORES: list[tuple[str, str, StoreTypeEnum, str]] = [
    ("JEWEL-01",     "Jewel Changi Airport",      StoreTypeEnum.flagship, "Jewel Changi"),
    ("BREEZE-01",    "Breeze by the East",        StoreTypeEnum.outlet,   "East Coast"),
    ("TAKA-01",      "Takashimaya Counter",       StoreTypeEnum.outlet,   "Ngee Ann City"),
    ("WORKSHOP-01",  "Victoria Enso Workshop",    StoreTypeEnum.warehouse, "Atelier"),
]


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

async def upsert_store(
    session: AsyncSession, code: str, name: str,
    store_type: StoreTypeEnum, location: str,
) -> Store:
    result = await session.execute(select(Store).where(Store.store_code == code))
    store = result.scalar_one_or_none()
    if store:
        return store
    from datetime import time as dtime
    store = Store(
        id=uuid.uuid4(),
        store_code=code,
        name=name,
        store_type=store_type,
        location=location,
        address=location,
        city="Singapore",
        country="Singapore",
        currency="SGD",
        business_hours_start=dtime(10, 0),
        business_hours_end=dtime(22, 0),
        is_active=True,
    )
    session.add(store)
    await session.flush()
    print(f"  Created store: {code} — {name}")
    return store


async def upsert_brand(session: AsyncSession, name: str, category_type: str) -> Brand:
    result = await session.execute(select(Brand).where(Brand.name == name))
    brand = result.scalar_one_or_none()
    if brand:
        return brand
    brand = Brand(id=uuid.uuid4(), name=name, category_type=category_type)
    session.add(brand)
    await session.flush()
    print(f"  Created brand: {name}")
    return brand


async def upsert_ve_categories(
    session: AsyncSession, store_id: uuid.UUID
) -> dict[str, Category]:
    """Build VE root + nested categories. Returns code → Category."""
    out: dict[str, Category] = {}

    # Root
    result = await session.execute(
        select(Category).where(
            Category.catg_code == VE_ROOT_CODE,
            Category.store_id == store_id,
        )
    )
    root = result.scalar_one_or_none()
    if not root:
        root = Category(
            id=uuid.uuid4(),
            store_id=store_id,
            catg_code=VE_ROOT_CODE,
            description="VICTORIA ENSO",
        )
        session.add(root)
        await session.flush()
        print(f"  Created root category: VE")
    out[VE_ROOT_CODE] = root

    # Two passes to respect parent_id FK ordering
    for parent_code, child_code, desc, cag_code in VE_TREE:
        parent = out.get(parent_code)
        result = await session.execute(
            select(Category).where(
                Category.catg_code == child_code,
                Category.store_id == store_id,
            )
        )
        cat = result.scalar_one_or_none()
        if not cat:
            cat = Category(
                id=uuid.uuid4(),
                store_id=store_id,
                catg_code=child_code,
                cag_catg_code=cag_code or None,
                description=desc,
                parent_id=parent.id if parent else None,
            )
            session.add(cat)
            await session.flush()
            print(f"    Created category: {child_code} — {desc}")
        else:
            # Re-parent / update CAG code if changed
            if parent and cat.parent_id != parent.id:
                cat.parent_id = parent.id
            if cag_code and cat.cag_catg_code != cag_code:
                cat.cag_catg_code = cag_code
        out[child_code] = cat

    return out


def derive_sale_ready(product: dict) -> bool:
    """A product is truly NEC-ready only if it has price + description + sale_ready flag."""
    return (
        bool(product.get("sale_ready"))
        and product.get("retail_price") is not None
        and bool(product.get("description"))
    )


def build_attributes(product: dict) -> dict:
    attrs: dict = {}
    for key in (
        "material", "category", "sources", "raw_names",
        "inventory_category",
    ):
        val = product.get(key)
        if val:
            attrs[key] = val
    # Preserve the old padded VE SKU code (e.g. VEBWLAMET0000062) for lookup
    old_code = product.get("sku_code")
    if old_code and old_code != product.get("internal_code"):
        attrs["ve_padded_code"] = old_code
    return attrs


def ve_product_type_enum(product: dict) -> ProductType:
    """Map JSON inventory_type → ProductType enum.

    JSON ``inventory_type`` is one of purchased/finished/material.
    ``material`` → material; ``finished`` → finished; ``purchased`` → finished
    (for the SKU, since the sourcing detail lives on Inventory).
    """
    inv_type = (product.get("inventory_type") or "").lower()
    if inv_type == "material":
        return ProductType.material
    sourcing = (product.get("sourcing_strategy") or "").lower()
    if sourcing.startswith("manufactured"):
        return ProductType.manufactured
    return ProductType.finished


# ------------------------------------------------------------------ #
# Main                                                                 #
# ------------------------------------------------------------------ #

async def main():
    connect_args: dict = {}
    if "127.0.0.1" in DATABASE_URL or "localhost" in DATABASE_URL:
        connect_args["ssl"] = False

    engine = create_async_engine(DATABASE_URL, connect_args=connect_args)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    products = json.loads(DATA_FILE.read_text())["products"]
    print(f"Loaded {len(products)} VE products from {DATA_FILE.name}\n")

    async with Session() as session:
        print("=== Ensuring stores ===")
        stores: dict[str, Store] = {}
        for code, name, store_type, location in REQUIRED_STORES:
            stores[code] = await upsert_store(session, code, name, store_type, location)

        print("\n=== Ensuring brand ===")
        brand = await upsert_brand(session, BRAND_NAME, "Jewellery & Decorative Arts")

        master_store = stores[SKU_MASTER_STORE]

        print("\n=== Ensuring VE category tree ===")
        cat_map = await upsert_ve_categories(session, master_store.id)

        print("\n=== Seeding SKU sequence counters ===")
        counters = await seed_counters_from_db(session)
        print(f"  Existing prefix counts: {len(counters)}")

        # --- Resolve category IDs for each JSON product_type ---
        pt_to_category: dict[str, Category] = {}
        for pt, code in PRODUCT_TYPE_TO_CATG.items():
            cat = cat_map.get(code)
            if cat:
                pt_to_category[pt] = cat
        fallback_cat = cat_map["VE_GF_GENERAL"]

        # --- Load products ---
        print(f"\n=== Loading {len(products)} products ===")
        created = updated = skipped = 0
        price_rows = plu_rows = inv_rows = 0

        for p in products:
            # Prefer the short VE internal code (A448); fall back to the padded
            # catalogue code (VELGMXXXX0000278) so that gemstones/crystals
            # without A-codes are still loaded.
            legacy_code = p.get("internal_code") or p.get("sku_code")
            if not legacy_code:
                skipped += 1
                continue
            legacy_code = legacy_code[:50]

            category = pt_to_category.get(p.get("product_type", ""), fallback_cat)
            product_type = ve_product_type_enum(p)
            attrs = build_attributes(p)
            sale_ready = derive_sale_ready(p)
            stocking_status = p.get("stocking_status") or None
            stocking_location = p.get("stocking_location") or None
            description = (p.get("description") or legacy_code)[:60]
            long_desc = (p.get("long_description") or "")[:1000] or None
            material_hint = p.get("material") or p.get("product_type") or ""
            cost_price = p.get("cost_price")

            # Look up existing SKU by legacy_code
            result = await session.execute(
                select(SKU).where(SKU.legacy_code == legacy_code)
            )
            sku = result.scalar_one_or_none()

            if sku:
                # Update fields (keep existing sku_code)
                sku.description = description
                sku.long_description = long_desc
                sku.cost_price = cost_price
                sku.category_id = category.id
                sku.brand_id = brand.id
                sku.product_type = product_type
                sku.form_factor = p.get("product_type")
                sku.attributes = attrs or None
                sku.status = "active" if sale_ready or stocking_status != "discontinued" else "draft"
                sku.sale_ready = sale_ready
                sku.stocking_status = stocking_status
                sku.primary_stocking_location = stocking_location
                sku.amazon_sku = p.get("amazon_sku")
                sku.google_product_id = p.get("google_product_id")
                sku.google_product_category = p.get("google_product_category")
                sku.use_stock = bool(p.get("use_stock", True))
                sku.block_sales = bool(p.get("block_sales", False))
                updated += 1
            else:
                new_code = await generate_code(
                    session,
                    category_description=category.description,
                    material_hint=material_hint,
                    counters=counters,
                )
                sku = SKU(
                    id=uuid.uuid4(),
                    store_id=master_store.id,
                    sku_code=new_code,
                    description=description,
                    long_description=long_desc,
                    cost_price=cost_price,
                    category_id=category.id,
                    brand_id=brand.id,
                    tax_code="G",
                    is_unique_piece=product_type == ProductType.manufactured,
                    use_stock=bool(p.get("use_stock", True)),
                    block_sales=bool(p.get("block_sales", False)),
                    product_type=product_type,
                    form_factor=p.get("product_type"),
                    attributes=attrs or None,
                    status="active" if sale_ready else "draft",
                    sale_ready=sale_ready,
                    stocking_status=stocking_status,
                    primary_stocking_location=stocking_location,
                    amazon_sku=p.get("amazon_sku"),
                    google_product_id=p.get("google_product_id"),
                    google_product_category=p.get("google_product_category"),
                    legacy_code=legacy_code,
                )
                session.add(sku)
                await session.flush()
                created += 1

            # PLU (NEC barcode)
            nec_plu = p.get("nec_plu")
            if nec_plu:
                result = await session.execute(
                    select(PLU).where(PLU.plu_code == str(nec_plu))
                )
                if not result.scalar_one_or_none():
                    session.add(PLU(
                        id=uuid.uuid4(),
                        plu_code=str(nec_plu)[:20],
                        sku_id=sku.id,
                    ))
                    plu_rows += 1

            # Retail price (only if provided)
            retail = p.get("retail_price")
            if retail:
                price_incl = Decimal(str(retail))
                price_excl = (price_incl / (1 + GST_RATE)).quantize(Decimal("0.01"))
                result = await session.execute(
                    select(Price).where(
                        Price.sku_id == sku.id,
                        Price.store_id == master_store.id,
                        Price.valid_to >= date.today(),
                    )
                )
                existing_price = result.scalar_one_or_none()
                if existing_price:
                    existing_price.price_incl_tax = price_incl
                    existing_price.price_excl_tax = price_excl
                else:
                    session.add(Price(
                        id=uuid.uuid4(),
                        sku_id=sku.id,
                        store_id=master_store.id,
                        price_incl_tax=price_incl,
                        price_excl_tax=price_excl,
                        price_unit=1,
                        valid_from=date.today(),
                        valid_to=FAR_FUTURE,
                    ))
                    price_rows += 1

            # Inventory at the right store
            target_store_code = LOCATION_TO_STORE.get(stocking_location or "")
            qty = int(p.get("qty_on_hand") or 0)
            if target_store_code:
                target_store = stores[target_store_code]
                location_state = (
                    InventoryLocationState.WORKSHOP
                    if stocking_location == "workshop"
                    else InventoryLocationState.STORE
                )
                result = await session.execute(
                    select(Inventory).where(
                        Inventory.sku_id == sku.id,
                        Inventory.store_id == target_store.id,
                    )
                )
                inv = result.scalar_one_or_none()
                if inv:
                    inv.qty_on_hand = qty
                    inv.last_updated = datetime.utcnow()
                    inv.location_status = location_state
                else:
                    session.add(Inventory(
                        id=uuid.uuid4(),
                        sku_id=sku.id,
                        store_id=target_store.id,
                        qty_on_hand=qty,
                        reorder_level=0,
                        reorder_qty=1,
                        last_updated=datetime.utcnow(),
                        location_status=location_state,
                        inventory_type=(
                            "material" if product_type == ProductType.material
                            else "finished" if product_type == ProductType.manufactured
                            else "purchased"
                        ),
                    ))
                    inv_rows += 1

            if (created + updated) % 100 == 0 and (created + updated):
                await session.flush()

        await session.commit()

        print(f"\nDone.")
        print(f"  SKUs created: {created}, updated: {updated}, skipped: {skipped}")
        print(f"  PLU rows added: {plu_rows}")
        print(f"  Price rows added: {price_rows}")
        print(f"  Inventory rows added: {inv_rows}")

        # Final sellability snapshot
        from sqlalchemy import func, text
        result = await session.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM skus WHERE brand_id = :b) AS ve_total,
              (SELECT COUNT(*) FROM skus WHERE brand_id = :b AND sale_ready) AS ve_sale_ready,
              (SELECT COUNT(*) FROM skus s
                 WHERE s.brand_id = :b AND s.sale_ready
                 AND EXISTS (
                   SELECT 1 FROM prices p
                   WHERE p.sku_id = s.id AND p.valid_to >= CURRENT_DATE
                 )
              ) AS ve_nec_ready
        """), {"b": brand.id})
        row = result.first()
        print(f"\n=== Sellability snapshot ===")
        print(f"  Total VE products:        {row.ve_total}")
        print(f"  sale_ready = true:        {row.ve_sale_ready}")
        print(f"  sale_ready + has price:   {row.ve_nec_ready}  <- will export to NEC POS")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
