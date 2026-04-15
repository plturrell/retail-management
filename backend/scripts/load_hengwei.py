"""Load Hengwei Craft supplier data: products from orders + purchase order records.

Extracted from:
  - docs/suppliers/hengweicraft/orders/1ef5751feb635b92294f8144d5d46e81.PNG (Order #364-365, 2025-02-28)
  - docs/suppliers/hengweicraft/orders/149.PNG (Order #149)
  - docs/suppliers/hengweicraft/catalog/ (two Excel catalogs for reference)

Usage:
    cd backend
    DATABASE_URL="postgresql+asyncpg://retailsg:RetailSG2026Secure@127.0.0.1:5434/retailsg" \
        python -m scripts.load_hengwei
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date, datetime
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.store import Store
from app.models.supplier import Supplier, SupplierProduct
from app.models.inventory import SKU, Category, Brand, Inventory
from app.models.user import User
from app.models.purchase import PurchaseOrder, PurchaseOrderItem, PurchaseOrderStatus

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://retailsg:RetailSG2026Secure@127.0.0.1:5434/retailsg",
)

STORE_CODE = "JEWEL-01"
SUPPLIER_CODE = "CN-001"
CNY_TO_SGD = Decimal("5.34")  # 1 SGD = 5.34 CNY

# ------------------------------------------------------------------ #
# Product data extracted from Hengwei order forms                      #
# ------------------------------------------------------------------ #

# Order #364-365 (2025-02-28) — extracted from order image
ORDER_364_365 = {
    "po_number": "HW-364-365",
    "order_date": date(2025, 2, 28),
    "items": [
        {"code": "A5304",   "qty": 120, "unit_cny": 5,    "desc": "Copper decoration, natural finish",           "materials": "Copper, Natural",             "size": "11.5x11.5x4"},
        {"code": "B14414",  "qty": 360, "unit_cny": 2,    "desc": "Small copper piece, natural green",           "materials": "Copper, Natural Green",        "size": "5M(2x4)"},
        {"code": "B14418",  "qty": 360, "unit_cny": 2,    "desc": "Small copper piece variant",                  "materials": "Copper, Natural",              "size": "5M(2x4)"},
        {"code": "B16068",  "qty": 200, "unit_cny": 2,    "desc": "Copper component",                            "materials": "Copper",                       "size": "small"},
        {"code": "B16068B", "qty": 200, "unit_cny": 2,    "desc": "Copper component variant B",                  "materials": "Copper",                       "size": "small"},
        {"code": "B19131",  "qty": 473, "unit_cny": 2,    "desc": "Copper natural work piece",                   "materials": "Copper, Natural",              "size": "small"},
        {"code": "H489A",   "qty": 1,   "unit_cny": 1490, "desc": "Malachite copper decoration set",             "materials": "Malachite, Copper, Natural",   "size": "12x12x48/40/34"},
        {"code": "A340",    "qty": 2,   "unit_cny": 1000, "desc": "Malachite tile decoration",                   "materials": "Malachite Tile",               "size": "large"},
        {"code": "A355",    "qty": 1,   "unit_cny": 1000, "desc": "Malachite piece",                             "materials": "Malachite, Green",             "size": "3M(5-12)"},
        {"code": "A4308",   "qty": 1,   "unit_cny": 473,  "desc": "Natural green stone decoration",              "materials": "Natural green stone",          "size": "53M(1C)"},
        {"code": "A0098",   "qty": 1,   "unit_cny": 525,  "desc": "Copper natural decoration, large",            "materials": "Copper, Natural",              "size": "11(H)x14(H)"},
        {"code": "A392",    "qty": 1,   "unit_cny": 976,  "desc": "Copper decoration with mineral accents",      "materials": "Copper, Mineral, Acrylic",     "size": "medium"},
        {"code": "A4298",   "qty": 1,   "unit_cny": 921,  "desc": "Blue crystal decoration",                     "materials": "Blue Crystal",                 "size": "medium"},
        {"code": "A031",    "qty": 1,   "unit_cny": 580,  "desc": "Natural white crystal decoration",            "materials": "Natural White Crystal, Copper", "size": "medium"},
    ],
    "wooden_frames_cny": 500,
    "total_cny": 34123,
    "payment_notes": "500 CNY via Alipay + 15,015 HKD + 23,550 HKD bank transfer to BOC HK (01271020007591 BKCHHKHH)",
}

# Order #149 — second order form (earlier order)
ORDER_149 = {
    "po_number": "HW-149",
    "order_date": date(2025, 1, 15),  # approximate date from order
    "items": [
        {"code": "A008",    "qty": 2,   "unit_cny": 290,  "desc": "Copper agate decoration",                     "materials": "Copper, Agate",                "size": "14x14x55"},
        {"code": "H1637A",  "qty": 1,   "unit_cny": 680,  "desc": "Copper crystal hanging decoration",           "materials": "Copper, K9 Crystal",           "size": "large"},
        {"code": "H594A",   "qty": 1,   "unit_cny": 850,  "desc": "Copper crystal decoration set A",             "materials": "Copper, K9 Crystal",           "size": "11x11x48"},
        {"code": "H523",    "qty": 1,   "unit_cny": 450,  "desc": "Copper crystal decoration",                   "materials": "Copper, Crystal",              "size": "12x12x35"},
        {"code": "A446",    "qty": 1,   "unit_cny": 780,  "desc": "Marble copper decoration",                    "materials": "Marble, Copper",               "size": "medium"},
        {"code": "A447",    "qty": 1,   "unit_cny": 650,  "desc": "Marble copper piece",                         "materials": "Marble, Copper",               "size": "medium"},
        {"code": "A448",    "qty": 1,   "unit_cny": 520,  "desc": "Crystal copper ornament",                     "materials": "Crystal, Copper",              "size": "medium"},
        {"code": "A449",    "qty": 1,   "unit_cny": 480,  "desc": "Crystal copper ornament variant",             "materials": "Crystal, Copper",              "size": "medium"},
        {"code": "H1022",   "qty": 1,   "unit_cny": 960,  "desc": "Large copper crystal display piece",          "materials": "Copper, Crystal",              "size": "22x11x35"},
        {"code": "B19131",  "qty": 200, "unit_cny": 2,    "desc": "Copper natural work piece",                   "materials": "Copper, Natural",              "size": "small"},
        {"code": "A5304",   "qty": 100, "unit_cny": 5,    "desc": "Copper decoration, natural finish",           "materials": "Copper, Natural",              "size": "11.5x11.5x4"},
    ],
    "wooden_frames_cny": 300,
    "total_cny": 11046,
    "payment_notes": "Paid cash at 5.34 CNY/SGD. Delivered — currently at Breeze by the East, moving to Jewel for 1 May 2026 opening.",
}

ORDERS = [ORDER_364_365, ORDER_149]


# ------------------------------------------------------------------ #
# Helpers                                                               #
# ------------------------------------------------------------------ #

async def get_or_create_category(session: AsyncSession, store_id: uuid.UUID) -> Category:
    """Get or create the 'Decorative Arts' category for Hengwei products."""
    code = "DECO-ARTS"
    result = await session.execute(
        select(Category).where(Category.catg_code == code, Category.store_id == store_id)
    )
    cat = result.scalar_one_or_none()
    if not cat:
        cat = Category(
            id=uuid.uuid4(),
            store_id=store_id,
            catg_code=code,
            description="Decorative Arts — Copper, Crystal, Marble, Malachite",
        )
        session.add(cat)
        await session.flush()
        print(f"  Created category: {code}")
    return cat


async def get_or_create_brand(session: AsyncSession) -> Brand:
    """Get or create the Hengwei Craft brand."""
    name = "Hengwei Craft"
    result = await session.execute(select(Brand).where(Brand.name == name))
    brand = result.scalar_one_or_none()
    if not brand:
        brand = Brand(id=uuid.uuid4(), name=name, category_type="Decorative Arts")
        session.add(brand)
        await session.flush()
        print(f"  Created brand: {name}")
    return brand


async def upsert_sku(
    session: AsyncSession,
    store_id: uuid.UUID,
    category_id: uuid.UUID,
    brand_id: uuid.UUID,
    code: str,
    desc: str,
    long_desc: str,
    cost_cny: Decimal,
) -> SKU:
    """Create or update a SKU."""
    result = await session.execute(
        select(SKU).where(SKU.sku_code == code, SKU.store_id == store_id)
    )
    sku = result.scalar_one_or_none()
    cost_sgd = (cost_cny / CNY_TO_SGD).quantize(Decimal("0.01"))

    if sku:
        sku.description = desc[:60]
        sku.long_description = long_desc[:1000]
        sku.cost_price = cost_sgd
        sku.category_id = category_id
        sku.brand_id = brand_id
    else:
        sku = SKU(
            id=uuid.uuid4(),
            store_id=store_id,
            sku_code=code,
            description=desc[:60],
            long_description=long_desc[:1000],
            cost_price=cost_sgd,
            category_id=category_id,
            brand_id=brand_id,
            tax_code="E",  # imported goods, GST on import
            is_unique_piece=cost_cny >= 400,  # higher-value pieces are unique
        )
        session.add(sku)
        await session.flush()

    return sku


async def ensure_inventory(session: AsyncSession, sku_id: uuid.UUID, store_id: uuid.UUID, qty: int = 1):
    """Create inventory record if it doesn't exist."""
    result = await session.execute(
        select(Inventory).where(Inventory.sku_id == sku_id, Inventory.store_id == store_id)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        inv = Inventory(
            id=uuid.uuid4(),
            sku_id=sku_id,
            store_id=store_id,
            qty_on_hand=qty,
            reorder_level=1,
            reorder_qty=1,
            last_updated=datetime.utcnow(),
        )
        session.add(inv)


async def link_supplier_product(
    session: AsyncSession,
    supplier_id: uuid.UUID,
    sku_id: uuid.UUID,
    code: str,
    cost_cny: Decimal,
):
    """Link SKU to supplier with cost in CNY."""
    result = await session.execute(
        select(SupplierProduct).where(
            SupplierProduct.supplier_id == supplier_id,
            SupplierProduct.sku_id == sku_id,
        )
    )
    sp = result.scalar_one_or_none()
    if not sp:
        sp = SupplierProduct(
            id=uuid.uuid4(),
            supplier_id=supplier_id,
            sku_id=sku_id,
            supplier_sku_code=code,
            supplier_unit_cost=cost_cny,
            currency="CNY",
            min_order_qty=1,
            lead_time_days=30,
            is_preferred=True,
        )
        session.add(sp)


# ------------------------------------------------------------------ #
# Main                                                                 #
# ------------------------------------------------------------------ #

async def main():
    connect_args: dict = {}
    if "127.0.0.1" in DATABASE_URL or "localhost" in DATABASE_URL:
        connect_args["ssl"] = False

    engine = create_async_engine(DATABASE_URL, connect_args=connect_args)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Look up store & supplier
        result = await session.execute(select(Store).where(Store.store_code == STORE_CODE))
        store = result.scalar_one_or_none()
        if not store:
            print(f"ERROR: Store {STORE_CODE} not found. Run load_suppliers.py first.")
            return

        result = await session.execute(select(Supplier).where(Supplier.supplier_code == SUPPLIER_CODE))
        supplier = result.scalar_one_or_none()
        if not supplier:
            print(f"ERROR: Supplier {SUPPLIER_CODE} not found. Run load_suppliers.py first.")
            return

        # Find a user for created_by
        result = await session.execute(select(User.id).limit(1))
        user_id = result.scalar_one_or_none()
        if not user_id:
            print("ERROR: No users in database. Log in via the app first to create a user.")
            return

        # Create category & brand
        print("\n=== Setting up Hengwei Craft products ===")
        category = await get_or_create_category(session, store.id)
        brand = await get_or_create_brand(session)

        # Collect all unique products across orders
        all_products: dict[str, dict] = {}
        for order in ORDERS:
            for item in order["items"]:
                code = item["code"]
                if code not in all_products or item["unit_cny"] > all_products[code]["unit_cny"]:
                    all_products[code] = item

        # Create SKUs
        print(f"\n=== Creating/updating {len(all_products)} SKUs ===")
        sku_map: dict[str, SKU] = {}
        for code, item in sorted(all_products.items()):
            long_desc = f"{item['desc']}. Materials: {item['materials']}. Size: {item['size']}. Supplier: Hengwei Craft (CN-001)."
            sku = await upsert_sku(
                session, store.id, category.id, brand.id,
                code, item["desc"], long_desc, Decimal(str(item["unit_cny"])),
            )
            sku_map[code] = sku
            await ensure_inventory(session, sku.id, store.id, qty=item.get("qty", 1))
            await link_supplier_product(session, supplier.id, sku.id, code, Decimal(str(item["unit_cny"])))
            print(f"  {code}: {item['desc'][:50]} — CNY {item['unit_cny']}")

        # Create purchase orders
        print(f"\n=== Creating purchase orders ===")
        for order_data in ORDERS:
            po_number = order_data["po_number"]

            # Delete existing PO to allow re-creation with corrected totals
            result = await session.execute(
                select(PurchaseOrder).where(PurchaseOrder.po_number == po_number)
            )
            existing_po = result.scalar_one_or_none()
            if existing_po:
                await session.delete(existing_po)
                await session.flush()
                print(f"  Replaced existing PO {po_number} with corrected totals")

            total_cny = Decimal(str(order_data["total_cny"]))
            total_sgd = (total_cny / CNY_TO_SGD).quantize(Decimal("0.01"))
            payment_notes = order_data.get("payment_notes", "")

            po = PurchaseOrder(
                id=uuid.uuid4(),
                po_number=po_number,
                store_id=store.id,
                supplier_id=supplier.id,
                order_date=order_data["order_date"],
                status=PurchaseOrderStatus.fully_received,
                subtotal=total_sgd,
                tax_total=Decimal("0"),
                grand_total=total_sgd,
                currency="SGD",
                notes=f"Hengwei Craft order. Total: CNY {total_cny:,.0f} @ {CNY_TO_SGD} = SGD {total_sgd:,.2f}. Frames: CNY {order_data['wooden_frames_cny']}. {payment_notes}"[:1000],
                created_by=user_id,
            )
            session.add(po)
            await session.flush()

            for item in order_data["items"]:
                sku = sku_map[item["code"]]
                line_cny = Decimal(str(item["qty"])) * Decimal(str(item["unit_cny"]))
                line_sgd = (line_cny / CNY_TO_SGD).quantize(Decimal("0.01"))

                po_item = PurchaseOrderItem(
                    id=uuid.uuid4(),
                    purchase_order_id=po.id,
                    sku_id=sku.id,
                    qty_ordered=item["qty"],
                    qty_received=item["qty"],
                    unit_cost=(Decimal(str(item["unit_cny"])) / CNY_TO_SGD).quantize(Decimal("0.01")),
                    tax_code="E",  # exempt — imported goods
                    line_total=line_sgd,
                )
                session.add(po_item)

            print(f"  Created PO {po_number}: {order_data['order_date']} — CNY {total_cny:,.0f} (SGD {total_sgd:,.2f}), {len(order_data['items'])} line items")

        await session.commit()
        print(f"\nDone. {len(all_products)} products + {len(ORDERS)} purchase orders loaded for Hengwei Craft.\n")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
