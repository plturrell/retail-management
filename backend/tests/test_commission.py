"""Unit tests for ``app.services.commission``.

Pure-logic module — no Firestore, no HTTP. Covers progressive-tier
calculation, the flat-rate fallback, ``parse_tiers`` deserialization,
and the rounding contract used downstream by payroll generation.
"""
from __future__ import annotations

from decimal import Decimal

from app.services.commission import (
    CommissionTier,
    calculate_commission,
    calculate_flat_commission,
    parse_tiers,
)


def D(value: str | int | float) -> Decimal:
    return Decimal(str(value))


# ── calculate_commission: degenerate inputs ────────────────────────────────

def test_zero_sales_returns_zero() -> None:
    tiers = [CommissionTier(min=D(0), max=None, rate=D("0.05"))]
    assert calculate_commission(D(0), tiers) == D(0)


def test_negative_sales_returns_zero() -> None:
    tiers = [CommissionTier(min=D(0), max=None, rate=D("0.05"))]
    assert calculate_commission(D("-100"), tiers) == D(0)


def test_empty_tiers_returns_zero() -> None:
    assert calculate_commission(D("1000"), []) == D(0)


# ── calculate_commission: single tier (flat) ───────────────────────────────

def test_single_unbounded_tier_acts_as_flat_rate() -> None:
    tiers = [CommissionTier(min=D(0), max=None, rate=D("0.05"))]
    assert calculate_commission(D("1000"), tiers) == D("50.00")


def test_single_capped_tier_pays_only_inside_bracket() -> None:
    tiers = [CommissionTier(min=D(0), max=D("1000"), rate=D("0.05"))]
    # Sales above cap: only first 1000 earns commission.
    assert calculate_commission(D("5000"), tiers) == D("50.00")


def test_sales_at_tier_min_pays_zero() -> None:
    """Boundary: sales == tier.min means *no sales above the floor*."""
    tiers = [CommissionTier(min=D("1000"), max=None, rate=D("0.10"))]
    assert calculate_commission(D("1000"), tiers) == D(0)


def test_sales_just_below_min_pays_zero() -> None:
    tiers = [CommissionTier(min=D("1000"), max=None, rate=D("0.10"))]
    assert calculate_commission(D("999.99"), tiers) == D(0)


# ── calculate_commission: progressive (multi-tier) ─────────────────────────

PROGRESSIVE_TIERS = [
    CommissionTier(min=D(0),    max=D("1000"), rate=D(0)),       # 0–1000 free
    CommissionTier(min=D("1000"), max=D("5000"), rate=D("0.05")),  # 1000–5000 @5%
    CommissionTier(min=D("5000"), max=None,    rate=D("0.10")),     # 5000+ @10%
]


def test_progressive_inside_first_paid_bracket() -> None:
    # 2500 sales → only 1500 falls in the 5% bracket.
    assert calculate_commission(D("2500"), PROGRESSIVE_TIERS) == D("75.00")


def test_progressive_at_top_bracket_boundary() -> None:
    # 5000 sales → exactly the 5% bracket fills (4000 * 0.05 = 200), 0 in top.
    assert calculate_commission(D("5000"), PROGRESSIVE_TIERS) == D("200.00")


def test_progressive_above_top_bracket() -> None:
    # 10000 sales → 4000*0.05 + 5000*0.10 = 200 + 500 = 700.
    assert calculate_commission(D("10000"), PROGRESSIVE_TIERS) == D("700.00")


def test_progressive_unsorted_input_is_sorted_internally() -> None:
    shuffled = list(reversed(PROGRESSIVE_TIERS))
    assert calculate_commission(D("10000"), shuffled) == D("700.00")


# ── calculate_commission: rounding ─────────────────────────────────────────

def test_rounding_half_up() -> None:
    # 100 * 0.0333 = 3.33  (ROUND_HALF_UP, 2dp)
    tiers = [CommissionTier(min=D(0), max=None, rate=D("0.0333"))]
    assert calculate_commission(D("100"), tiers) == D("3.33")


def test_rounding_at_half_breaks_up() -> None:
    # 333 * 0.05 = 16.65 (no rounding needed); use 333.33 * 0.05 = 16.6665 → 16.67
    tiers = [CommissionTier(min=D(0), max=None, rate=D("0.05"))]
    assert calculate_commission(D("333.33"), tiers) == D("16.67")


# ── calculate_flat_commission ──────────────────────────────────────────────

def test_flat_zero_sales() -> None:
    assert calculate_flat_commission(D(0), D("0.05")) == D(0)


def test_flat_zero_rate() -> None:
    assert calculate_flat_commission(D("1000"), D(0)) == D(0)


def test_flat_negative_sales() -> None:
    assert calculate_flat_commission(D("-100"), D("0.05")) == D(0)


def test_flat_normal() -> None:
    assert calculate_flat_commission(D("2500"), D("0.05")) == D("125.00")


def test_flat_rounds_half_up() -> None:
    # 100 * 0.0333 = 3.33
    assert calculate_flat_commission(D("100"), D("0.0333")) == D("3.33")


# ── parse_tiers ────────────────────────────────────────────────────────────

def test_parse_tiers_from_list_of_dicts() -> None:
    raw = [{"min": "0", "max": "1000", "rate": "0.05"}, {"min": 1000, "max": None, "rate": 0.10}]
    parsed = parse_tiers(raw)
    assert len(parsed) == 2
    assert parsed[0].min == D(0) and parsed[0].max == D("1000") and parsed[0].rate == D("0.05")
    assert parsed[1].max is None and parsed[1].rate == D("0.1")


def test_parse_tiers_from_json_string() -> None:
    raw = '[{"min": 0, "max": null, "rate": 0.07}]'
    parsed = parse_tiers(raw)
    assert len(parsed) == 1 and parsed[0].max is None and parsed[0].rate == D("0.07")


def test_parse_tiers_missing_max_treated_as_unlimited() -> None:
    raw = [{"min": 0, "rate": 0.05}]  # no "max" key
    parsed = parse_tiers(raw)
    assert parsed[0].max is None
