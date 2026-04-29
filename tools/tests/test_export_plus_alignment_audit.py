from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from export_plus_alignment_audit import (
    SourcePlusRow,
    build_alignment_audit,
    build_summary,
)
from identifier_utils import generate_nec_plu


def test_build_alignment_audit_classifies_misaligned_swap_candidates():
    rows = [
        SourcePlusRow(
            sku_code="VESCUCOPP0000502",
            legacy_code="A010B",
            description="Copper Sculpture",
            form_factor="Sculpture",
            plu_code=generate_nec_plu(503),
        ),
        SourcePlusRow(
            sku_code="VESCUCOPP0000503",
            legacy_code="A010C",
            description="Copper Sculpture",
            form_factor="Sculpture",
            plu_code=generate_nec_plu(502),
        ),
    ]

    audit_rows = build_alignment_audit(rows)

    assert len(audit_rows) == 2
    first = audit_rows[0]
    assert first.sku_format == "ve_7digit_sequence"
    assert first.row_status == "misaligned_valid"
    assert first.target_status == "occupied_by_misaligned_valid"
    assert first.target_sku_code == "VESCUCOPP0000503"
    assert first.recommended_action == "swap_or_staged_realign"


def test_build_alignment_audit_marks_invalid_row_with_free_target():
    rows = [
        SourcePlusRow(
            sku_code="VESCUCOPP0000502",
            legacy_code="A010B",
            description="Copper Sculpture",
            form_factor="Sculpture",
            plu_code="2000000005011",
        ),
    ]

    audit_rows = build_alignment_audit(rows)

    assert len(audit_rows) == 1
    row = audit_rows[0]
    assert row.sku_format == "ve_7digit_sequence"
    assert row.row_status == "invalid"
    assert row.target_status == "free"
    assert row.expected_aligned_plu == generate_nec_plu(502)
    assert row.recommended_action == "set_to_aligned"


def test_build_summary_reports_counts():
    rows = [
        SourcePlusRow(
            sku_code="VESCUCOPP0000502",
            legacy_code="A010B",
            description="Copper Sculpture",
            form_factor="Sculpture",
            plu_code="2000000005011",
        ),
        SourcePlusRow(
            sku_code="VESCUCOPP0000503",
            legacy_code="A010C",
            description="Copper Sculpture",
            form_factor="Sculpture",
            plu_code=generate_nec_plu(503),
        ),
    ]
    audit_rows = build_alignment_audit(rows, include_aligned=True)
    summary = build_summary(rows, audit_rows, include_aligned=True)

    assert summary["total_plus_rows"] == 2
    assert summary["csv_row_count"] == 2
    assert summary["row_status_counts"] == {"invalid": 1, "aligned": 1}


def test_build_alignment_audit_marks_legacy_gen_rows_as_unmapped():
    rows = [
        SourcePlusRow(
            sku_code="GEN-CRY-000001",
            legacy_code="H489A",
            description="Crystal Bookend",
            form_factor="Bookend",
            plu_code="2000000000671",
        ),
    ]

    audit_rows = build_alignment_audit(rows)

    assert len(audit_rows) == 1
    row = audit_rows[0]
    assert row.sku_format == "legacy_gen"
    assert row.row_status == "legacy_valid_unmapped"
    assert row.target_status == "no_sequence_rule"
    assert row.recommended_action == "manual_review_define_legacy_mapping"
