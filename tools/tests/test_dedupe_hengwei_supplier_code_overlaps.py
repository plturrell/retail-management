from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from dedupe_hengwei_supplier_code_overlaps import (
    LinkStats,
    SkuSnapshot,
    build_overlap_pair,
    choose_best_description,
    choose_canonical_side,
    merge_attributes,
)


def _links(
    *,
    inventory_qty: int = 0,
    inventory_rows: int = 0,
    prices: int = 0,
    promotions: int = 0,
    order_items: int = 0,
    purchase_order_items: int = 0,
    supplier_products: int = 0,
    plus_rows: int = 1,
) -> LinkStats:
    return LinkStats(
        inventory_qty=inventory_qty,
        inventory_rows=inventory_rows,
        prices=prices,
        promotions=promotions,
        order_items=order_items,
        purchase_order_items=purchase_order_items,
        supplier_products=supplier_products,
        plus_rows=plus_rows,
    )


def _snapshot(
    *,
    sku_id: str,
    sku_code: str,
    description: str,
    long_description: str = "",
    form_factor: str | None = None,
    legacy_code: str | None = None,
    supplier_code: str | None = None,
    store_id: str = "store-1",
    store_code: str | None = "JEWEL-01",
    attributes: dict | None = None,
    links: LinkStats | None = None,
) -> SkuSnapshot:
    return SkuSnapshot(
        sku_id=sku_id,
        store_id=store_id,
        store_code=store_code,
        sku_code=sku_code,
        legacy_code=legacy_code,
        supplier_code=supplier_code,
        description=description,
        long_description=long_description or description,
        form_factor=form_factor,
        cost_price=None,
        attributes=attributes or {},
        links=links or _links(),
    )


def test_choose_best_description_prefers_specific_text():
    assert choose_best_description("decoration", "figurine made of crystal and metal") == "figurine made of crystal and metal"


def test_choose_canonical_side_prefers_supplier_and_po_history():
    rebuilt = _snapshot(
        sku_id="rebuilt",
        sku_code="VEDECFLUO0000567",
        description="decoration",
        links=_links(purchase_order_items=1, supplier_products=1),
    )
    ve = _snapshot(
        sku_id="ve",
        sku_code="VEFIGCRYS0000056",
        description="figurine made of crystal and metal",
        legacy_code="A008",
        links=_links(inventory_qty=2),
    )

    assert choose_canonical_side(rebuilt, ve) == "rebuilt"


def test_merge_attributes_marks_deduped_overlap():
    merged = merge_attributes(
        {"previous_sku_code": "DEC-CPR-000001"},
        {"ve_padded_code": "VEDECFLUO0000567"},
        supplier_code="A008",
        duplicate_sku_code="VEFIGCRYS0000056",
        duplicate_sku_id="ve-id",
        merged_form_factor="Figurine",
        merged_description="figurine made of crystal and metal",
    )

    assert merged["supplier_sku_code"] == "A008"
    assert merged["deduped_supplier_overlap"] is True
    assert merged["merged_duplicate_sku_code"] == "VEFIGCRYS0000056"


def test_build_overlap_pair_reuses_existing_ve_identifier_but_keeps_rebuilt_canonical_row():
    rebuilt = _snapshot(
        sku_id="rebuilt-id",
        sku_code="VEDECFLUO0000567",
        description="decoration",
        long_description="decoration. Model: A008.",
        form_factor="Decorative Object",
        supplier_code="A008",
        attributes={"previous_sku_code": "DEC-CPR-000001"},
        links=_links(inventory_qty=2, purchase_order_items=1, supplier_products=1),
    )
    ve = _snapshot(
        sku_id="ve-id",
        sku_code="VEFIGCRYS0000056",
        description="figurine made of crystal and metal",
        long_description="figurine made of crystal and metal.",
        form_factor="Figurine",
        legacy_code="A008",
        supplier_code="A008",
        attributes={"legacy_source": "master"},
        links=_links(),
    )

    pair = build_overlap_pair(rebuilt, ve, supplier_code="A008", ve_plu_code="2000000000565")

    assert pair.canonical.sku_id == "rebuilt-id"
    assert pair.duplicate.sku_id == "ve-id"
    assert pair.preferred_identifier_sku_code == "VEFIGCRYS0000056"
    assert pair.preferred_identifier_plu_code == "2000000000565"
    assert pair.merged_description == "figurine made of crystal and metal"
    assert pair.merged_form_factor == "Figurine"
