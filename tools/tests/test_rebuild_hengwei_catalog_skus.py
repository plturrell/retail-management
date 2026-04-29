from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from identifier_utils import aligned_nec_plu_for_sku, generate_nec_plu
from rebuild_hengwei_catalog_skus import (
    LiveSkuRow,
    build_catalog_index,
    catalog_lookup_keys,
    derive_form_factor,
    derive_material,
    plan_rebuilds,
    resolve_catalog_match,
)


def test_catalog_lookup_keys_expands_variant_codes():
    assert catalog_lookup_keys("H1402ABC") == ["H1402ABC", "H1402A", "H1402"]
    assert catalog_lookup_keys("H180A/B") == ["H180A / B", "H180A", "H180"]


def test_resolve_catalog_match_falls_back_to_base_code_variant():
    catalog_index = build_catalog_index(
        [
            {
                "supplier_item_codes": ["H1402A", "H1402B", "H1402C"],
                "primary_supplier_item_code": "H1402A",
                "display_name": "decoration",
                "size": "9*9*15",
                "materials": "copper",
                "catalog_file": "catalog/home.xlsx",
                "sheet_name": "可订做产品",
            }
        ]
    )

    match = resolve_catalog_match("H1402ABC", catalog_index)

    assert match is not None
    assert match.match_strategy == "base_code"
    assert match.display_name == "decoration"
    assert match.sheet_name == "可订做产品"


def test_derive_form_factor_prefers_structural_prefix_for_wall_art():
    row = LiveSkuRow(
        sku_id="sku-1",
        store_id="store-1",
        store_code="JEWEL-01",
        old_sku_code="WAL-CPR-000001",
        supplier_sku_code="A340",
        description="decoration",
        long_description="decoration. Materials: copper marble. Model: A340.",
        attributes={"materials": "copper marble"},
        cost_price=88.58,
        qty_on_hand=2,
    )

    assert derive_form_factor(row, None) == "Wall Art"


def test_derive_material_falls_back_to_old_code_segment():
    row = LiveSkuRow(
        sku_id="sku-1",
        store_id="store-1",
        store_code="JEWEL-01",
        old_sku_code="DEC-MAL-000001",
        supplier_sku_code="A340",
        description="decoration",
        long_description="decoration",
        attributes={},
        cost_price=88.58,
        qty_on_hand=2,
    )

    assert derive_material(row, None) == "Malachite"


def test_plan_rebuilds_generates_aligned_identifiers_and_preserves_previous_code():
    rows = [
        LiveSkuRow(
            sku_id="sku-1",
            store_id="store-1",
            store_code="JEWEL-01",
            old_sku_code="CUS-CPR-000013",
            supplier_sku_code="H1548",
            description="tray — copper marble",
            long_description="tray. Materials: copper marble. Size: 40*40*6. Model: H1548.",
            attributes={"materials": "copper marble", "size": "40*40*6"},
            cost_price=243.45,
            qty_on_hand=0,
        )
    ]
    catalog_index = build_catalog_index(
        [
            {
                "supplier_item_codes": ["H1548"],
                "primary_supplier_item_code": "H1548",
                "display_name": "tray",
                "size": "40*40*6",
                "materials": "copper marble",
                "catalog_file": "catalog/home.xlsx",
                "sheet_name": "可订做产品",
            }
        ]
    )

    plans = plan_rebuilds(
        rows,
        catalog_index,
        existing_sku_codes={"VEFIGCRYS0000056"},
        existing_plus={generate_nec_plu(56)},
    )

    assert len(plans) == 1
    plan = plans[0]
    assert plan.form_factor == "Tray"
    assert plan.material == "Marble"
    assert plan.new_sku_code == "VETRYMARB0000057"
    assert plan.new_plu_code == aligned_nec_plu_for_sku(plan.new_sku_code)
    assert plan.attributes["previous_sku_code"] == "CUS-CPR-000013"
    assert plan.attributes["ve_padded_code"] == plan.new_sku_code
