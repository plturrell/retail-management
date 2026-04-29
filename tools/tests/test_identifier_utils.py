from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from identifier_utils import (
    aligned_nec_plu_for_sku,
    allocate_identifier_pair,
    generate_nec_plu,
    is_valid_ean13,
    parse_sku_sequence,
    validate_identifier_pair,
)


def test_generate_nec_plu_is_valid_ean13():
    plu = generate_nec_plu(502)

    assert plu == "2000000005027"
    assert is_valid_ean13(plu)


def test_allocate_identifier_pair_keeps_sku_and_plu_aligned():
    existing_sku_codes = {"VEDECMARB0000501"}
    existing_plus = {generate_nec_plu(501)}

    sku_code, plu_code, next_seq = allocate_identifier_pair(
        lambda seq: f"VEDECMARB{seq:07d}",
        existing_sku_codes,
        existing_plus,
        501,
    )

    assert sku_code == "VEDECMARB0000502"
    assert plu_code == generate_nec_plu(502)
    assert next_seq == 503


def test_validate_identifier_pair_rejects_invalid_plu():
    with pytest.raises(ValueError, match="Invalid EAN-13"):
        validate_identifier_pair("VESCUCOPP0000502", "2000000005011")


def test_validate_identifier_pair_rejects_misaligned_but_valid_plu():
    with pytest.raises(ValueError, match="does not align"):
        validate_identifier_pair("VESCUCOPP0000502", generate_nec_plu(503))


def test_aligned_nec_plu_for_sku_uses_sku_sequence():
    sku_code = "VESCUCOPP0000502"

    assert parse_sku_sequence(sku_code) == 502
    assert aligned_nec_plu_for_sku(sku_code) == generate_nec_plu(502)
