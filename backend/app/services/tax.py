"""Singapore GST tax calculation service.

Current GST rate: 9% (effective 1 Jan 2024).
All prices in the system are stored as price_incl_tax (GST-inclusive).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

# Singapore GST rate — change here if the rate updates
GST_RATE = Decimal("0.09")

# Tax codes: G = GST-taxable, E = exempt, Z = zero-rated
TAX_CODE_RATES: dict[str, Decimal] = {
    "G": GST_RATE,
    "E": Decimal("0"),
    "Z": Decimal("0"),
}


def tax_rate_for_code(tax_code: str) -> Decimal:
    """Return the tax rate for a given tax code."""
    return TAX_CODE_RATES.get(tax_code.upper(), GST_RATE)


def compute_tax_from_inclusive(price_incl_tax: Decimal, tax_code: str = "G") -> Decimal:
    """Extract GST component from a GST-inclusive price.

    Formula: tax = price_incl / (1 + rate) * rate
    """
    rate = tax_rate_for_code(tax_code)
    if rate == 0:
        return Decimal("0.00")
    return (price_incl_tax / (1 + rate) * rate).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def price_excl_from_inclusive(price_incl_tax: Decimal, tax_code: str = "G") -> Decimal:
    """Derive the GST-exclusive price from an inclusive price."""
    return (price_incl_tax - compute_tax_from_inclusive(price_incl_tax, tax_code)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def compute_line_tax(
    unit_price_incl: float,
    qty: int,
    discount_per_unit: float = 0.0,
    tax_code: str = "G",
) -> float:
    """Compute total tax for a line item after discount."""
    net = Decimal(str(unit_price_incl)) - Decimal(str(discount_per_unit))
    if net <= 0:
        return 0.0
    line_total = net * qty
    return float(compute_tax_from_inclusive(line_total, tax_code))
