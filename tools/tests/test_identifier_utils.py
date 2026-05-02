from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from identifier_utils import (
    aligned_nec_plu_for_sku,
    allocate_identifier_pair,
    compute_ean8_check_digit,
    generate_nec_plu,
    is_valid_ean8,
    is_valid_ean13,
    parse_sku_sequence,
    validate_identifier_pair,
)


def test_generate_nec_plu_is_valid_ean8_seq_1():
    # seq=1 → body "2000001" → check 1 → "20000011"
    # (the 13 Hengwei homeware labels start here)
    plu = generate_nec_plu(1)

    assert plu == "20000011"
    assert is_valid_ean8(plu)
    assert len(plu) == 8


def test_generate_nec_plu_is_valid_ean8_seq_502():
    plu = generate_nec_plu(502)

    assert is_valid_ean8(plu)
    assert plu.startswith("2")
    assert len(plu) == 8


def test_compute_ean8_check_digit_known_values():
    # Verified against an external EAN-8 calculator.
    assert compute_ean8_check_digit("2000001") == "1"  # → 20000011 (label #1)
    assert compute_ean8_check_digit("2000002") == "8"  # → 20000028 (label #2)
    assert compute_ean8_check_digit("2000013") == "4"  # → 20000134 (label #13)
    # Standard GTIN-8 spec test vector
    assert compute_ean8_check_digit("1234567") == "0"  # → 12345670


def test_generate_nec_plu_rejects_overflow():
    with pytest.raises(ValueError, match="exceeds"):
        generate_nec_plu(1_000_000)


def test_legacy_ean13_validator_still_recognises_old_codes():
    # Used by migration tooling that reads pre-switch data. Not for new allocs.
    assert is_valid_ean13("2000000005027")
    assert not is_valid_ean13("20000011")  # EAN-8, not EAN-13


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
    with pytest.raises(ValueError, match="Invalid EAN-8"):
        # bad check digit
        validate_identifier_pair("VESCUCOPP0000502", "20000010")


def test_validate_identifier_pair_rejects_misaligned_but_valid_plu():
    with pytest.raises(ValueError, match="does not align"):
        validate_identifier_pair("VESCUCOPP0000502", generate_nec_plu(503))


def test_aligned_nec_plu_for_sku_uses_sku_sequence():
    sku_code = "VESCUCOPP0000502"

    assert parse_sku_sequence(sku_code) == 502
    assert aligned_nec_plu_for_sku(sku_code) == generate_nec_plu(502)
