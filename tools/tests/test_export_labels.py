from __future__ import annotations

import sys
from pathlib import Path

# Allow importing from the tools/scripts directory
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from export_labels import (
    CAG_CATEGORY_LABEL,
    PILLAR_MAP,
    _box_label_row,
    _catalogue_type,
    _clean_text,
    _item_label_row,
)


def test_catalogue_type_prefers_form_factor_for_db_rows():
    product = {"product_type": "finished", "form_factor": "Bookend"}

    assert _catalogue_type(product) == "Bookend"
    assert _catalogue_type(product) in PILLAR_MAP["homeware"]


def test_catalogue_type_falls_back_to_json_product_type():
    product = {"product_type": "Sculpture"}

    assert _catalogue_type(product) == "Sculpture"
    assert _catalogue_type(product) in PILLAR_MAP["homeware"]


def test_label_rows_use_catalogue_type_for_display_and_category():
    product = {
        "sku_code": "VEHOME0001",
        "nec_plu": "2000000000001",
        "description": "Quartz Bookend",
        "product_type": "finished",
        "form_factor": "Bookend",
        "retail_price": 120,
        "qty_on_hand": 3,
    }

    item_row = _item_label_row(product)
    box_row = _box_label_row(product)

    assert item_row[5] == "Bookend"
    assert item_row[6] == CAG_CATEGORY_LABEL["Bookend"]
    assert box_row[5] == "Bookend"


def test_null_like_values_are_cleaned_for_export_text_fields():
    product = {
        "sku_code": "VEHOME0002",
        "nec_plu": "2000000000002",
        "description": "Decorative Object",
        "product_type": "finished",
        "form_factor": "Decorative Object",
        "internal_code": "NULL",
        "primary_stocking_location": "warehouse",
    }

    item_row = _item_label_row(product)
    box_row = _box_label_row(product)

    assert _clean_text("NULL") == ""
    assert item_row[10] == ""
    assert box_row[10] == "warehouse"
    assert box_row[11] == ""
