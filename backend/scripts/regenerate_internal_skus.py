"""Regenerate internal SKU codes for all existing products.

What this does
--------------
1. Rebuilds the Hengwei category hierarchy under a root ``Hengwei Decorative
   Arts`` category (parent_id links).
2. For every SKU whose ``sku_code`` does NOT match our internal pattern
   ``{L1}-{L2}-{SEQ6}``:
     a. Ensures a ``SupplierProduct`` row exists with ``supplier_sku_code`` set
        to the original code.
     b. Generates a new internal code using ``services.sku_codes``.
     c. Extracts structured attributes (material, size, color, dimensions)
        from ``long_description`` into the new ``attributes`` JSONB.
     d. Sets ``product_type = 'finished'`` (all Hengwei items are finished).
     e. Updates the SKU row.
3. Idempotent — re-running is safe. SKUs already matching the pattern are
   skipped. SupplierProduct rows are upserted by (supplier_id, sku_id).

Usage::

    cd backend
    DATABASE_URL="..." python -m scripts.regenerate_internal_skus
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.inventory import SKU, Category, ProductType
from app.models.supplier import Supplier, SupplierProduct
from app.services.sku_codes import (
    _PREFIX_RE,
    classify_l1,
    classify_l2,
    generate_code,
    seed_counters_from_db,
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://retailsg:RetailSG2026Secure@127.0.0.1:5434/retailsg",
)

HENGWEI_SUPPLIER_CODE = "CN-001"

# Sheet name → (subcategory code, description)
# These are the leaf categories under the Hengwei Decorative Arts root.
SUBCATEGORIES = {
    "摆件":           ("HW-DECORATIONS", "Decorations (摆件)"),
    "花瓶":           ("HW-VASES",       "Vases (花瓶)"),
    "托盘+盒子":      ("HW-TRAYS",       "Trays & Boxes (托盘+盒子)"),
    "挂画":           ("HW-WALLART",     "Wall Art (挂画)"),
    "铜、水晶系列1":  ("HW-CC1",         "Copper & Crystal Series 1"),
    "铜、水晶系列2":  ("HW-CC2",         "Copper & Crystal Series 2"),
    "铜、水晶系列3":  ("HW-CC3",         "Copper & Crystal Series 3"),
    "铜、水晶系列4":  ("HW-CC4",         "Copper & Crystal Series 4"),
    "铜、水晶系列5":  ("HW-CC5",         "Copper & Crystal Series 5"),
    "挂饰系列6":      ("HW-HANGING",     "Hanging Decorations (挂饰)"),
    "可订做产品":     ("HW-CUSTOM",      "Custom Products (可订做)"),
}


# ------------------------------------------------------------------ #
# Attribute extraction                                                 #
# ------------------------------------------------------------------ #

_SIZE_RE = re.compile(r"Size:\s*([^.]+?)\.", re.IGNORECASE)
_MAT_RE = re.compile(r"Materials?:\s*([^.]+?)\.", re.IGNORECASE)
_COLOR_RE = re.compile(r"Color:\s*([^.]+?)\.", re.IGNORECASE)
_MODEL_RE = re.compile(r"Model:\s*([^.]+?)\.", re.IGNORECASE)
_CATALOG_RE = re.compile(r"Catalog:\s*([^.]+?)\.", re.IGNORECASE)


def extract_attributes(long_description: str | None) -> dict:
    if not long_description:
        return {}
    attrs: dict = {}
    for key, regex in (
        ("size", _SIZE_RE),
        ("materials", _MAT_RE),
        ("color", _COLOR_RE),
        ("model", _MODEL_RE),
        ("catalog", _CATALOG_RE),
    ):
        m = regex.search(long_description)
        if m:
            attrs[key] = m.group(1).strip()
    return attrs


# ------------------------------------------------------------------ #
# Category hierarchy                                                   #
# ------------------------------------------------------------------ #

async def ensure_category_hierarchy(session: AsyncSession, store_id: uuid.UUID) -> dict:
    """Build ``Hengwei Decorative Arts`` root + subcategories.

    Returns map of ``sheet_name`` → ``Category``.
    """
    # Root
    result = await session.execute(
        select(Category).where(
            Category.catg_code == "HW-ROOT",
            Category.store_id == store_id,
        )
    )
    root = result.scalar_one_or_none()
    if not root:
        root = Category(
            id=uuid.uuid4(),
            store_id=store_id,
            catg_code="HW-ROOT",
            description="Hengwei Decorative Arts",
        )
        session.add(root)
        await session.flush()
        print(f"  Created root category: {root.description}")

    sheet_to_cat: dict[str, Category] = {}
    for sheet_name, (code, desc) in SUBCATEGORIES.items():
        result = await session.execute(
            select(Category).where(
                Category.catg_code == code,
                Category.store_id == store_id,
            )
        )
        cat = result.scalar_one_or_none()
        if not cat:
            cat = Category(
                id=uuid.uuid4(),
                store_id=store_id,
                catg_code=code,
                description=desc,
                parent_id=root.id,
            )
            session.add(cat)
            await session.flush()
            print(f"    Created subcategory: {desc}")
        elif cat.parent_id != root.id:
            cat.parent_id = root.id
            await session.flush()
            print(f"    Re-parented: {desc}")
        sheet_to_cat[sheet_name] = cat

    return sheet_to_cat


# ------------------------------------------------------------------ #
# Main regeneration                                                    #
# ------------------------------------------------------------------ #

async def main():
    connect_args: dict = {}
    if "127.0.0.1" in DATABASE_URL or "localhost" in DATABASE_URL:
        connect_args["ssl"] = False

    engine = create_async_engine(DATABASE_URL, connect_args=connect_args)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # Load supplier
        result = await session.execute(
            select(Supplier).where(Supplier.supplier_code == HENGWEI_SUPPLIER_CODE)
        )
        supplier = result.scalar_one_or_none()
        if not supplier:
            print(f"ERROR: Supplier {HENGWEI_SUPPLIER_CODE} not found.")
            return

        # All SKUs linked to Hengwei via SupplierProduct
        result = await session.execute(
            select(SKU)
            .join(SupplierProduct, SupplierProduct.sku_id == SKU.id)
            .where(SupplierProduct.supplier_id == supplier.id)
        )
        skus = result.scalars().unique().all()
        print(f"Found {len(skus)} SKUs linked to {HENGWEI_SUPPLIER_CODE}.")

        if not skus:
            return

        store_id = skus[0].store_id
        print("\n=== Ensuring category hierarchy ===")
        sheet_to_cat = await ensure_category_hierarchy(session, store_id)

        # Reverse map category_id → sheet_name so we can re-categorise existing
        # SKUs into the new hierarchy too.
        cat_id_to_sheet: dict[uuid.UUID, str] = {}
        for sheet_name, (code, _) in SUBCATEGORIES.items():
            result = await session.execute(
                select(Category).where(
                    Category.catg_code == code, Category.store_id == store_id
                )
            )
            cat = result.scalar_one()
            cat_id_to_sheet[cat.id] = sheet_name

        # Also pick up the legacy per-sheet codes we used in load_hengwei_catalog.py
        # (HW-DECORATIONSB, HW-VASES, etc.) so we can migrate them.
        result = await session.execute(
            select(Category).where(
                Category.store_id == store_id,
                Category.catg_code.like("HW-%"),
            )
        )
        legacy_cats = {c.catg_code: c for c in result.scalars().all()}

        # Seed sequence counters
        print("\n=== Seeding sequence counters ===")
        counters = await seed_counters_from_db(session)
        print(f"  Existing prefix counts: {len(counters)}")

        # Iterate SKUs, regenerate codes
        print(f"\n=== Regenerating codes for {len(skus)} SKUs ===")
        regenerated = 0
        skipped = 0

        for sku in skus:
            if sku.sku_code and _PREFIX_RE.match(sku.sku_code):
                skipped += 1
                continue

            # Find current catalog sheet from long_description → Catalog:
            catalog_match = _CATALOG_RE.search(sku.long_description or "")
            sheet_name = None
            if catalog_match:
                cat_tag = catalog_match.group(1).strip()
                # Format "Idaho 2026/摆件"
                if "/" in cat_tag:
                    sheet_name = cat_tag.split("/", 1)[1].strip()

            target_cat = sheet_to_cat.get(sheet_name) if sheet_name else None
            if target_cat is None:
                # Fallback: keep existing category if it's in the new hierarchy,
                # else assign to Decorations.
                if sku.category_id in cat_id_to_sheet:
                    target_cat = next(
                        c for c in sheet_to_cat.values() if c.id == sku.category_id
                    )
                else:
                    target_cat = sheet_to_cat["摆件"]

            attrs = extract_attributes(sku.long_description)
            material_hint = attrs.get("materials") or attrs.get("color") or target_cat.description

            original_supplier_code = sku.sku_code

            # Generate new internal code
            new_code = await generate_code(
                session,
                category_description=target_cat.description,
                material_hint=material_hint,
                counters=counters,
            )

            # Update SKU
            sku.sku_code = new_code
            sku.category_id = target_cat.id
            sku.product_type = ProductType.finished
            sku.attributes = attrs or None
            sku.status = "active"

            # Upsert SupplierProduct — set supplier_sku_code to the original
            result = await session.execute(
                select(SupplierProduct).where(
                    SupplierProduct.supplier_id == supplier.id,
                    SupplierProduct.sku_id == sku.id,
                )
            )
            sp = result.scalar_one_or_none()
            if sp:
                if not sp.supplier_sku_code:
                    sp.supplier_sku_code = original_supplier_code[:100]
            else:
                session.add(SupplierProduct(
                    id=uuid.uuid4(),
                    supplier_id=supplier.id,
                    sku_id=sku.id,
                    supplier_sku_code=original_supplier_code[:100],
                    supplier_unit_cost=sku.cost_price or 0,
                    currency="CNY",
                    min_order_qty=1,
                    lead_time_days=30,
                    is_preferred=True,
                ))

            regenerated += 1
            if regenerated % 100 == 0:
                print(f"  ... {regenerated} regenerated")
                await session.flush()

        await session.commit()
        print(f"\nDone. Regenerated: {regenerated}, Skipped (already internal): {skipped}")

        # Summary by prefix
        result = await session.execute(
            select(SKU.sku_code).where(
                SKU.store_id == store_id,
            )
        )
        prefix_counts: dict[str, int] = {}
        for (code,) in result.all():
            m = _PREFIX_RE.match(code or "")
            if not m:
                continue
            prefix = f"{m.group(1)}-{m.group(2)}"
            prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1

        print("\nInternal SKU codes by prefix:")
        for prefix, count in sorted(prefix_counts.items(), key=lambda x: -x[1]):
            print(f"  {prefix}: {count}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
