"""
Commission calculation service.

Pure calculation module — no database access.
Follows the same pattern as cpf.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional


@dataclass
class CommissionResult:
    sales_amount: Decimal
    commission_amount: Decimal
    rule_name: str


@dataclass
class CommissionTier:
    min: Decimal
    max: Optional[Decimal]  # None = unlimited
    rate: Decimal


def _round_commission(amount: Decimal) -> Decimal:
    """Round to 2 decimal places."""
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_tiers(tiers_data: str | list) -> list[CommissionTier]:
    """Parse tiers from a JSON string or a list of dicts into CommissionTier list.

    Accepts either a JSON string (legacy SQLAlchemy storage) or a native list
    (Firestore storage).
    """
    if isinstance(tiers_data, str):
        raw = json.loads(tiers_data)
    else:
        raw = tiers_data
    result = []
    for t in raw:
        result.append(CommissionTier(
            min=Decimal(str(t["min"])),
            max=Decimal(str(t["max"])) if t.get("max") is not None else None,
            rate=Decimal(str(t["rate"])),
        ))
    return result


def calculate_commission(
    sales_amount: Decimal,
    tiers: list[CommissionTier],
) -> Decimal:
    """
    Calculate tiered commission.

    Each tier defines a bracket: sales between tier.min and tier.max
    are charged at tier.rate. Tiers are applied cumulatively (like
    progressive tax brackets).

    For a flat commission, supply a single tier with min=0, max=None.

    Args:
        sales_amount: Total sales for the period.
        tiers: Ordered list of commission tiers.

    Returns:
        Total commission amount.
    """
    if sales_amount <= 0:
        return Decimal("0")

    # Sort tiers by min to ensure correct ordering
    sorted_tiers = sorted(tiers, key=lambda t: t.min)
    total_commission = Decimal("0")

    for tier in sorted_tiers:
        tier_min = tier.min
        tier_max = tier.max if tier.max is not None else sales_amount

        if sales_amount <= tier_min:
            break

        # Amount of sales that falls within this tier
        applicable = min(sales_amount, tier_max) - tier_min
        if applicable > 0:
            total_commission += _round_commission(applicable * tier.rate)

    return _round_commission(total_commission)


def calculate_flat_commission(
    sales_amount: Decimal,
    rate: Decimal,
) -> Decimal:
    """
    Calculate flat-rate commission (convenience wrapper).

    Args:
        sales_amount: Total sales for the period.
        rate: Commission rate as decimal (e.g. 0.05 for 5%).

    Returns:
        Commission amount.
    """
    if sales_amount <= 0 or rate <= 0:
        return Decimal("0")
    return _round_commission(sales_amount * rate)
