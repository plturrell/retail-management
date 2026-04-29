"""Tests for ``app.services.nec_jewel_preview``."""
from __future__ import annotations

from app.services.nec_jewel_preview import build_preview


def _good_product(**overrides):
    base = {
        "sku_code": "VE0001",
        "description": "Test SKU",
        "brand_name": "VICTORIA ENSO",
        "age_group": "ADULT",
        "gender": "UNISEX",
        "cost_price": 10.0,
        "retail_price": 109.0,
        "price_excl_tax": 100.0,
        "nec_plu": "8881234567890",
        "qty_on_hand": 5,
    }
    base.update(overrides)
    return base


def test_preview_clean_run_has_no_errors():
    products = [_good_product(), _good_product(sku_code="VE0002")]
    excluded: list[dict] = []
    result = build_preview(
        products, excluded,
        tenant_code="200151", nec_store_id="80001", taxable=True,
    )
    assert result.is_ready
    assert result.sellable_count == 2
    assert result.errors == []
    # SKU/PLU/PRICE rows: one per product. PROMO: 6 tiers × 2 SKUs = 12.
    assert result.counts["sku"] == 2
    assert result.counts["plu"] == 2
    assert result.counts["price"] == 2
    assert result.counts["promo"] == 12
    assert result.counts["invdetails"] == 2
    # CATG count comes from the 5-row tenant tree.
    assert result.counts["catg"] >= 3


def test_preview_flags_long_sku_code():
    products = [_good_product(sku_code="X" * 17)]
    result = build_preview(products, [], tenant_code="200151", nec_store_id="80001", taxable=True)
    assert any(i.field == "sku_code" and i.severity == "error" for i in result.errors)
    assert not result.is_ready


def test_preview_flags_missing_description_as_error():
    products = [_good_product(description="")]
    result = build_preview(products, [], tenant_code="200151", nec_store_id="80001", taxable=True)
    assert any(i.field == "description" and i.severity == "error" for i in result.errors)


def test_preview_truncation_warning_for_long_description():
    products = [_good_product(description="A" * 80)]
    result = build_preview(products, [], tenant_code="200151", nec_store_id="80001", taxable=True)
    msgs = [i.message for i in result.warnings if i.field == "description"]
    assert any("truncate" in m.lower() for m in msgs)


def test_preview_invalid_age_group_is_error():
    products = [_good_product(age_group="TEEN")]
    result = build_preview(products, [], tenant_code="200151", nec_store_id="80001", taxable=True)
    assert any(i.field == "age_group" for i in result.errors)


def test_preview_missing_price_omits_price_row():
    products = [_good_product(retail_price=None, price_excl_tax=None)]
    result = build_preview(products, [], tenant_code="200151", nec_store_id="80001", taxable=True)
    assert result.counts["price"] == 0
    assert any(i.field == "retail_price" for i in result.errors)


def test_preview_missing_plu_warns_and_skips_row():
    products = [_good_product(nec_plu=None)]
    result = build_preview(products, [], tenant_code="200151", nec_store_id="80001", taxable=True)
    assert result.counts["plu"] == 0
    assert any(i.field == "nec_plu" and i.severity == "warning" for i in result.warnings)


def test_preview_excluded_summary_aggregates_reasons():
    excluded = [
        {"sku_code": "X1", "sale_ready": False, "status": "active", "has_price": True, "has_plu": True, "description": "x"},
        {"sku_code": "X2", "sale_ready": True, "status": "active", "has_price": False, "has_plu": True, "description": "x"},
        {"sku_code": "X3", "sale_ready": True, "status": "active", "has_price": True, "has_plu": False, "description": "x"},
    ]
    result = build_preview([], excluded, tenant_code="200151", nec_store_id="80001", taxable=True)
    assert result.excluded_summary["not_sale_ready"] == 1
    assert result.excluded_summary["no_active_price"] == 1
    assert result.excluded_summary["no_plu"] == 1
    assert not result.is_ready  # sellable_count is 0


def test_preview_duplicate_sku_codes_flagged():
    products = [_good_product(), _good_product()]  # both VE0001
    result = build_preview(products, [], tenant_code="200151", nec_store_id="80001", taxable=True)
    assert any("Duplicate" in i.message for i in result.errors)


def test_preview_ratio_drift_for_landside():
    # incl=120, excl=100 -> ratio 1.20 vs expected ~1.09 -> warning.
    products = [_good_product(retail_price=120.0, price_excl_tax=100.0)]
    result = build_preview(products, [], tenant_code="200151", nec_store_id="80001", taxable=True)
    assert any(i.field == "price_excl_tax" and i.severity == "warning" for i in result.warnings)


def test_preview_airside_requires_equal_incl_and_excl():
    products = [_good_product(retail_price=109.0, price_excl_tax=100.0)]
    result = build_preview(products, [], tenant_code="200151", nec_store_id="80001", taxable=False)
    assert any(i.field == "price_excl_tax" for i in result.warnings)
