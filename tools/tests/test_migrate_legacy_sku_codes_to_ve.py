from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from migrate_legacy_sku_codes_to_ve import MigrationRow, summarize


def test_summarize_counts_rows_and_types():
    rows = [
        MigrationRow(
            sku_id="1",
            store_id="store-1",
            old_sku_code="GEN-CRY-000001",
            new_sku_code="VEBKECRYS0000067",
            legacy_code="H489A",
            description="Crystal Bookend",
            form_factor="Bookend",
            plu_code="2000000000671",
        ),
        MigrationRow(
            sku_id="2",
            store_id="store-1",
            old_sku_code="GEN-CRY-000010",
            new_sku_code="VESCUCRYS0000077",
            legacy_code="H904B",
            description="Decorative Marble and Crystal Sculpture",
            form_factor="Sculpture",
            plu_code="2000000000770",
        ),
    ]

    result = summarize(rows)

    assert result["count"] == 2
    assert result["by_type"] == {"Bookend": 1, "Sculpture": 1}
    assert result["sample"][0]["old_sku_code"] == "GEN-CRY-000001"
    assert result["sample"][0]["new_sku_code"] == "VEBKECRYS0000067"
