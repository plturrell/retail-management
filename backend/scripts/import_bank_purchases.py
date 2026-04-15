"""Import historical purchases from bank statement CSV into PurchaseOrders.

Idempotent — skips rows where po_number (= reference) already exists.

Usage:
    DATABASE_URL="postgresql+asyncpg://retailsg:RetailSG2026Secure@127.0.0.1:5434/retailsg" \
        python -m scripts.import_bank_purchases data/bank_purchases_template.csv
"""
from __future__ import annotations

import asyncio
import csv
import os
import sys
import uuid
from datetime import date as date_type, datetime
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.store import Store
from app.models.supplier import Supplier
from app.models.user import User
from app.models.purchase import PurchaseOrder, PurchaseOrderItem, PurchaseOrderStatus
from app.models.inventory import SKU

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://retailsg:RetailSG2026Secure@127.0.0.1:5434/retailsg",
)

STORE_CODE = "JEWEL-01"
GST_RATE = Decimal("0.09")


async def get_or_create_bulk_sku(session: AsyncSession, store_id: uuid.UUID) -> SKU:
    """Get or create a placeholder SKU for bulk/unitemized bank statement purchases."""
    code = "BULK-PURCHASE"
    result = await session.execute(
        select(SKU).where(SKU.sku_code == code, SKU.store_id == store_id)
    )
    sku = result.scalar_one_or_none()
    if not sku:
        sku = SKU(
            id=uuid.uuid4(),
            store_id=store_id,
            sku_code=code,
            description="Bulk purchase (bank statement import)",
            long_description="Placeholder SKU for bank statement imports where individual line items are not available.",
            block_sales=True,
        )
        session.add(sku)
        await session.flush()
        print(f"  Created placeholder SKU: {code}")
    return sku


async def find_system_user(session: AsyncSession) -> uuid.UUID:
    """Find first user in the database to use as created_by for historical POs."""
    result = await session.execute(select(User.id).limit(1))
    row = result.scalar_one_or_none()
    if not row:
        raise RuntimeError("No users in database. Create at least one user first (via Firebase auth).")
    return row


async def main(csv_path: str):
    connect_args: dict = {}
    if "127.0.0.1" in DATABASE_URL or "localhost" in DATABASE_URL:
        connect_args["ssl"] = False

    engine = create_async_engine(DATABASE_URL, connect_args=connect_args)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Look up store
        result = await session.execute(select(Store).where(Store.store_code == STORE_CODE))
        store = result.scalar_one_or_none()
        if not store:
            print(f"ERROR: Store {STORE_CODE} not found. Run load_suppliers.py first.")
            return

        # Look up all suppliers by code
        result = await session.execute(select(Supplier))
        suppliers = {s.supplier_code: s for s in result.scalars().all()}

        # System user for created_by
        system_user_id = await find_system_user(session)

        # Placeholder SKU for bulk items
        bulk_sku = await get_or_create_bulk_sku(session, store.id)

        # Read CSV
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = [r for r in reader]

        print(f"\n=== Importing {len(rows)} rows from {csv_path} ===\n")

        created = 0
        skipped = 0
        errors = 0

        for i, row in enumerate(rows, start=2):  # row 2+ in CSV (header is row 1)
            ref = (row.get("reference") or "").strip()
            supplier_code = (row.get("supplier_code") or "").strip()
            date_str = (row.get("date") or "").strip()
            description = (row.get("description") or "").strip()
            amount_str = (row.get("amount") or "").strip()
            currency = (row.get("currency") or "SGD").strip().upper()
            fx_rate_str = (row.get("fx_rate_to_sgd") or "").strip()

            # Skip blank/instruction rows
            if not ref or not date_str or not amount_str:
                continue

            # Check for duplicate
            existing = await session.execute(
                select(PurchaseOrder.id).where(PurchaseOrder.po_number == ref)
            )
            if existing.scalar_one_or_none():
                print(f"  SKIP row {i}: PO {ref} already exists")
                skipped += 1
                continue

            # Validate supplier
            supplier = suppliers.get(supplier_code)
            if not supplier:
                print(f"  ERROR row {i}: Unknown supplier_code '{supplier_code}' — skipping")
                errors += 1
                continue

            # Parse
            try:
                order_date = date_type.fromisoformat(date_str)
            except ValueError:
                print(f"  ERROR row {i}: Invalid date '{date_str}' — skipping")
                errors += 1
                continue

            try:
                amount = Decimal(amount_str)
            except Exception:
                print(f"  ERROR row {i}: Invalid amount '{amount_str}' — skipping")
                errors += 1
                continue

            fx_rate = Decimal(fx_rate_str) if fx_rate_str else None

            # Convert to SGD for totals
            if currency == "SGD" or not fx_rate:
                sgd_amount = amount
                fx_note = ""
            else:
                sgd_amount = (amount / fx_rate).quantize(Decimal("0.01"))
                fx_note = f" | Original: {currency} {amount:,.2f} @ {fx_rate} = SGD {sgd_amount:,.2f}"

            # For Singapore suppliers with GST
            if supplier.gst_registered:
                tax_code = "G"
                subtotal = (sgd_amount / (1 + GST_RATE)).quantize(Decimal("0.01"))
                tax_total = sgd_amount - subtotal
            else:
                tax_code = "E"
                subtotal = sgd_amount
                tax_total = Decimal("0")

            notes = f"Bank statement import: {description}{fx_note}"

            po = PurchaseOrder(
                id=uuid.uuid4(),
                po_number=ref,
                store_id=store.id,
                supplier_id=supplier.id,
                order_date=order_date,
                status=PurchaseOrderStatus.fully_received,
                subtotal=subtotal,
                tax_total=tax_total,
                grand_total=sgd_amount,
                currency="SGD",
                notes=notes[:1000],
                created_by=system_user_id,
            )
            session.add(po)
            await session.flush()

            po_item = PurchaseOrderItem(
                id=uuid.uuid4(),
                purchase_order_id=po.id,
                sku_id=bulk_sku.id,
                qty_ordered=1,
                qty_received=1,
                unit_cost=subtotal,
                tax_code=tax_code,
                line_total=sgd_amount,
            )
            session.add(po_item)

            print(f"  Created PO {ref}: {supplier_code} — SGD {sgd_amount:,.2f} ({description})")
            created += 1

        await session.commit()
        print(f"\nDone. Created: {created}, Skipped: {skipped}, Errors: {errors}\n")

    await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.import_bank_purchases <csv_path>")
        print("Example: python -m scripts.import_bank_purchases data/bank_purchases_template.csv")
        sys.exit(1)

    asyncio.run(main(sys.argv[1]))
