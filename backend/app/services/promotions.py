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

from app.firestore_helpers import query_collection


async def best_discount_for_sku(
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

    # Fetch promotions targeting this SKU
    promos = query_collection("promotions", filters=[("sku_id", "==", str(sku_id))])

    # Also fetch category-level promotions
    if category_id is not None:
        cat_promos = query_collection("promotions", filters=[("category_id", "==", str(category_id))])
        # Deduplicate by id
        seen = {p.get("id") for p in promos}
        for p in cat_promos:
            if p.get("id") not in seen:
                promos.append(p)

    if not promos:
        return 0.0

    best = Decimal("0")
    price = Decimal(str(unit_price))

    for promo in promos:
        method = (promo.get("disc_method", "") or "").upper()
        value = Decimal(str(promo.get("disc_value", 0)))

        if method == "PERCENT":
            disc = (price * value / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif method == "AMOUNT":
            disc = min(value, price)
        elif method == "BOGO":
            free_items = qty // 2
            disc = (price * free_items / qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if qty > 0 else Decimal("0")
        else:
            disc = Decimal("0")

        if disc > best:
            best = disc

    return float(best)
