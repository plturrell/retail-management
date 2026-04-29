"""Smoke tests for ``app.services.nec_jewel_bundle``."""
from __future__ import annotations

import zipfile
from datetime import datetime
from io import BytesIO

from app.services import nec_jewel_bundle as bundle


SAMPLE_PRODUCTS = [
    {
        "sku_code": "VE-001",
        "description": "Rose Quartz Bracelet",
        "long_description": "Hand-strung rose quartz bracelet",
        "form_factor": "Bracelet",
        "cost_price": 35.0,
        "retail_price": 109.0,  # SGD inclusive at 9% GST → excl 100.00
        "qty_on_hand": 12,
        "nec_plu": "8881234560011",
    },
    {
        "sku_code": "VE-002",
        "description": "Amethyst Pendant",
        "form_factor": "Pendant",
        "cost_price": 25.0,
        "retail_price": 89.0,
        "qty_on_hand": 0,  # excluded from INVDETAILS
        # No PLU → excluded from PLU
    },
]


def test_bundle_generates_all_six_files():
    now = datetime(2024, 6, 1, 9, 0, 0)
    result = bundle.build_master_bundle(
        SAMPLE_PRODUCTS,
        tenant_code="200151",
        store_id="80001",
        taxable=True,
        now=now,
    )
    names = sorted(result.files.keys())
    assert names == sorted([
        "CATG_200151_20240601090000.txt",
        "SKU_80001_20240601090000.txt",
        "PLU_200151_20240601090000.txt",
        "PRICE_200151_20240601090000.txt",
        "INVDETAILS_80001_20240601090000.txt",
        "PROMO_200151_20240601090000.txt",
    ])


def test_price_derives_excl_tax_for_taxable_store():
    result = bundle.build_master_bundle(
        SAMPLE_PRODUCTS, tenant_code="T", store_id="S", taxable=True
    )
    price_payload = next(v for k, v in result.files.items() if k.startswith("PRICE_")).decode()
    # 109.00 incl + 9% GST → 100.00 excl
    assert "A,VE-001,,109.00,100.00,1," in price_payload


def test_price_uses_excl_equals_incl_for_airside_store():
    result = bundle.build_master_bundle(
        SAMPLE_PRODUCTS, tenant_code="T", store_id="S", taxable=False
    )
    price_payload = next(v for k, v in result.files.items() if k.startswith("PRICE_")).decode()
    assert "A,VE-001,,109.00,109.00,1," in price_payload


def test_invdetails_skips_zero_qty():
    result = bundle.build_master_bundle(
        SAMPLE_PRODUCTS, tenant_code="T", store_id="S",
    )
    inv_payload = next(v for k, v in result.files.items() if k.startswith("INVDETAILS_")).decode()
    # Only VE-001 (qty=12) — VE-002 (qty=0) is excluded.
    assert ",VE-001,Update,12\r\n" in inv_payload
    assert "VE-002" not in inv_payload
    assert result.counts["invdetails"] == 1


def test_plu_skips_products_without_barcode():
    result = bundle.build_master_bundle(SAMPLE_PRODUCTS, tenant_code="T", store_id="S")
    plu_payload = next(v for k, v in result.files.items() if k.startswith("PLU_")).decode()
    assert "VE-001" in plu_payload
    assert "VE-002" not in plu_payload
    assert result.counts["plu"] == 1


def test_zip_round_trips_each_file():
    result = bundle.build_master_bundle(SAMPLE_PRODUCTS, tenant_code="T", store_id="S")
    zip_bytes = result.as_zip()
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        names = set(zf.namelist())
        assert names == set(result.files.keys())


def test_promo_can_be_disabled():
    result = bundle.build_master_bundle(
        SAMPLE_PRODUCTS, tenant_code="T", store_id="S", include_promo=False
    )
    assert not any(k.startswith("PROMO_") for k in result.files)


def test_inventory_can_be_disabled():
    result = bundle.build_master_bundle(
        SAMPLE_PRODUCTS, tenant_code="T", store_id="S", include_inventory=False
    )
    assert not any(k.startswith("INVDETAILS_") for k in result.files)
