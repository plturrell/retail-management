"""Promotion engine — auto-applies active promotions to order line items.

Supports discount methods:
  - PERCENT: percentage off the unit price
  - AMOUNT: fixed dollar amount off the unit price
  - BOGO: buy-one-get-one (applies 100% discount to every 2nd item)
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import Promotion


async def best_discount_for_sku(
    db: AsyncSession,
    sku_id: UUID,
    category_id: Optional[UUID],
    unit_price: float,
    qty: int,
    today: Optional[date] = None,
) -> float:
    """Return the best per-unit discount amount for a SKU.

    Checks both SKU-level and category-level promotions, picks whichever
    gives the customer the bigger discount.
    """
    if today is None:
        today = date.today()

    # Fetch promotions targeting this SKU and/or its category (OR)
    criteria = [Promotion.sku_id == sku_id]
    if category_id is not None:
        criteria.append(Promotion.category_id == category_id)
    query = select(Promotion).where(or_(*criteria))
    result = await db.execute(query)
    promos = result.scalars().all()

    if not promos:
        return 0.0

    best = Decimal("0")
    price = Decimal(str(unit_price))

    for promo in promos:
        method = promo.disc_method.upper()
        value = Decimal(str(promo.disc_value))

        if method == "PERCENT":
            disc = (price * value / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif method == "AMOUNT":
            disc = min(value, price)
        elif method == "BOGO":
            # Discount = price of every 2nd item spread across all items
            free_items = qty // 2
            disc = (price * free_items / qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if qty > 0 else Decimal("0")
        else:
            disc = Decimal("0")

        if disc > best:
            best = disc

    return float(best)
