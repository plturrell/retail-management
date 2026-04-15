"""Load supplier templates for 4 sourcing regions into PostgreSQL.

Idempotent — upserts by supplier_code. Safe to re-run.

Usage:
    # With Cloud SQL proxy running on port 5434:
    DATABASE_URL="postgresql+asyncpg://retailsg:RetailSG2026Secure@127.0.0.1:5434/retailsg" \
        python -m scripts.load_suppliers
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import time

# Allow running as `python -m scripts.load_suppliers` from backend/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.store import Store, StoreTypeEnum
from app.models.supplier import Supplier

# ------------------------------------------------------------------ #
# Configuration                                                        #
# ------------------------------------------------------------------ #

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://retailsg:RetailSG2026Secure@127.0.0.1:5434/retailsg",
)

STORES = [
    {
        "store_code": "JEWEL-01",
        "name": "Jewel Changi Airport",
        "store_type": StoreTypeEnum.flagship,
        "location": "Jewel Changi Airport, #02-234",
        "address": "78 Airport Boulevard, Jewel Changi Airport, Singapore 819666",
        "city": "Singapore",
        "country": "Singapore",
        "postal_code": "819666",
        "currency": "SGD",
        "business_hours_start": time(10, 0),
        "business_hours_end": time(22, 0),
        "is_active": True,
    },
    {
        "store_code": "BREEZE-01",
        "name": "Breeze by the East",
        "store_type": StoreTypeEnum.warehouse,
        "location": "Breeze by the East (home / temp warehouse)",
        "address": "Breeze by the East, Singapore",
        "city": "Singapore",
        "country": "Singapore",
        "currency": "SGD",
        "business_hours_start": time(9, 0),
        "business_hours_end": time(21, 0),
        "is_active": True,
    },
]

SUPPLIERS = [
    {
        "supplier_code": "SG-001",
        "name": "Singapore Supplier (TBC)",
        "country": "Singapore",
        "currency": "SGD",
        "payment_terms_days": 30,
        "gst_registered": True,
        "notes": "Local Singapore supplier — update with real company name, contact, and bank details.",
    },
    {
        "supplier_code": "TH-001",
        "name": "Thailand Supplier (TBC)",
        "country": "Thailand",
        "currency": "THB",
        "payment_terms_days": 45,
        "gst_registered": False,
        "notes": "Thai supplier — update with real company name, contact, and bank details. FX rate ~24 THB per 1 SGD.",
    },
    {
        "supplier_code": "CN-001",
        "name": "Hengwei Craft (衡威工艺)",
        "country": "China",
        "currency": "CNY",
        "payment_terms_days": 60,
        "gst_registered": False,
        "address": "Shiling Town, Huadu District, Guangzhou (广州市花都区狮岭镇). Factory: Xinhui District, Jiangmen (江门市新会区)",
        "bank_account": "01271020007591",
        "bank_name": "Bank of China (Hong Kong) — SWIFT: BKCHHKHH",
        "notes": "Copper, crystal, malachite, marble decorative arts. Payments via HKD bank transfer to BOC HK + Alipay. Two catalogs: Idaho 2026 + Home 2026.",
    },
    {
        "supplier_code": "OL-001",
        "name": "Online Supplier (TBC)",
        "country": "Online",
        "currency": "SGD",
        "payment_terms_days": 0,
        "gst_registered": False,
        "notes": "Online marketplace/platform — update with platform name and account details.",
    },
]


# ------------------------------------------------------------------ #
# Upsert helpers                                                       #
# ------------------------------------------------------------------ #

async def upsert_store(session: AsyncSession, store_data: dict) -> Store:
    result = await session.execute(
        select(Store).where(Store.store_code == store_data["store_code"])
    )
    store = result.scalar_one_or_none()

    if store:
        for k, v in store_data.items():
            setattr(store, k, v)
        print(f"  Updated store: {store.store_code} — {store.name}")
    else:
        store = Store(id=uuid.uuid4(), **store_data)
        session.add(store)
        print(f"  Created store: {store.store_code} — {store.name}")

    return store


async def upsert_supplier(session: AsyncSession, data: dict) -> Supplier:
    result = await session.execute(
        select(Supplier).where(Supplier.supplier_code == data["supplier_code"])
    )
    supplier = result.scalar_one_or_none()

    if supplier:
        for k, v in data.items():
            setattr(supplier, k, v)
        print(f"  Updated supplier: {supplier.supplier_code} — {supplier.name} ({supplier.country})")
    else:
        supplier = Supplier(id=uuid.uuid4(), **data)
        session.add(supplier)
        print(f"  Created supplier: {data['supplier_code']} — {data['name']} ({data['country']})")

    return supplier


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
        print("\n=== Loading Stores ===")
        for store_data in STORES:
            await upsert_store(session, store_data)

        print("\n=== Loading Supplier Templates ===")
        for supplier_data in SUPPLIERS:
            await upsert_supplier(session, supplier_data)

        await session.commit()
        print(f"\nDone. {len(STORES)} stores + {len(SUPPLIERS)} supplier templates loaded.\n")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
