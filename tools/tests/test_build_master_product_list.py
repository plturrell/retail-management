"""Unit tests for the master product list builder.

Tests cover normalization, material extraction, product type extraction,
SKU generation, deduplication, and NEC PLU check-digit calculation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Allow importing from the tools/scripts directory
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_master_product_list import (
    ALL_PRODUCT_TYPES,
    MasterProduct,
    RawProduct,
    deduplicate_products,
    extract_material,
    extract_product_type,
    generate_amazon_sku,
    generate_google_product_id,
    generate_nec_plu,
    generate_sku_code,
    normalize_text,
    validate_master_identifiers,
)


# ── normalize_text ──────────────────────────────────────────────────────────

class TestNormalizeText:
    def test_lowercases(self):
        assert normalize_text("HELLO World") == "hello world"

    def test_strips_special_chars(self):
        assert normalize_text("rose-quartz (100%)") == "rose quartz 100"

    def test_collapses_whitespace(self):
        assert normalize_text("  a   b  c ") == "a b c"

    def test_empty(self):
        assert normalize_text("") == ""


# ── extract_material ────────────────────────────────────────────────────────

class TestExtractMaterial:
    def test_finds_amethyst(self):
        assert extract_material("Purple Amethyst Bracelet 8mm") == "Amethyst"

    def test_finds_rose_quartz(self):
        assert extract_material("rose quartz heart pendant") == "Rose Quartz"

    def test_longest_match_first(self):
        assert extract_material("watermelon tourmaline bead") == "Watermelon Tourmaline"

    def test_no_match(self):
        assert extract_material("plastic toy car") == ""

    def test_case_insensitive(self):
        assert extract_material("JADE BANGLE") == "Jade"


# ── extract_product_type ────────────────────────────────────────────────────

class TestExtractProductType:
    def test_bracelet(self):
        assert extract_product_type("Amethyst Bracelet 10mm") == "Bracelet"

    def test_necklace(self):
        assert extract_product_type("Gold Necklace Chain") == "Necklace"

    def test_figurine(self):
        assert extract_product_type("Crystal Figurine Cat") == "Figurine"

    def test_wall_art(self):
        assert extract_product_type("Agate Wall Decor Slice") == "Wall Art"

    def test_unknown_defaults_to_loose_gemstone(self):
        assert extract_product_type("Something Random") == "Loose Gemstone"

    def test_loose_gemstone(self):
        assert extract_product_type("Loose Amethyst stone") == "Loose Gemstone"

    def test_tumbled_stone(self):
        assert extract_product_type("Tumbled Rose Quartz") == "Tumbled Stone"

    def test_raw_specimen(self):
        assert extract_product_type("Raw Quartz Specimen") == "Raw Specimen"

    def test_crystal_cluster(self):
        assert extract_product_type("Amethyst Cluster Large") == "Crystal Cluster"

    def test_decorative_object(self):
        assert extract_product_type("Marble Decorative Item") == "Decorative Object"

    def test_bead(self):
        assert extract_product_type("Jade Bead 8mm") == "Gemstone Bead"


# ── generate_sku_code ───────────────────────────────────────────────────────

class TestGenerateSkuCode:
    def test_bracelet_quartz(self):
        result = generate_sku_code("A008", "Quartz", "Bracelet", 1)
        assert result.startswith("VEBRA")
        assert len(result) == 16

    def test_length_always_16(self):
        result = generate_sku_code("H1063", "Watermelon Tourmaline", "Necklace", 999)
        assert len(result) == 16

    def test_loose_gemstone_type(self):
        result = generate_sku_code("", "", "Loose Gemstone", 42)
        assert "LGM" in result


class TestAllProductTypes:
    def test_no_other_in_types(self):
        assert "Other" not in ALL_PRODUCT_TYPES

    def test_extract_never_returns_other(self):
        for desc in ["xyz", "unknown thing", "", "random text", "item"]:
            result = extract_product_type(desc)
            assert result != "Other", f"extract_product_type({desc!r}) returned 'Other'"


# ── generate_amazon_sku ─────────────────────────────────────────────────────

class TestGenerateAmazonSku:
    def test_format(self):
        result = generate_amazon_sku("A008", "Amethyst", "Bracelet")
        assert result == "VE-AMETHYST-BRAC-A008"

    def test_no_code(self):
        result = generate_amazon_sku("", "Jade", "Ring")
        assert result.endswith("-NOCODE")

    def test_strips_special_chars(self):
        result = generate_amazon_sku("X1", "Rose Quartz", "Pendant")
        assert " " not in result


# ── generate_google_product_id ──────────────────────────────────────────────

class TestGenerateGoogleProductId:
    def test_format(self):
        result = generate_google_product_id("VEBRAQRTZ0000001")
        assert result == "online:en:SG:VEBRAQRTZ0000001"


# ── generate_nec_plu ────────────────────────────────────────────────────────

class TestGenerateNecPlu:
    def test_length_13(self):
        result = generate_nec_plu(1)
        assert len(result) == 13

    def test_starts_with_200(self):
        result = generate_nec_plu(42)
        assert result.startswith("200")

    def test_check_digit_valid(self):
        plu = generate_nec_plu(1)
        digits = [int(d) for d in plu[:12]]
        total = sum(d * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits))
        expected = (10 - (total % 10)) % 10
        assert int(plu[12]) == expected

    def test_unique_for_different_seq(self):
        assert generate_nec_plu(1) != generate_nec_plu(2)


# ── deduplicate_products ────────────────────────────────────────────────────

class TestDeduplicateProducts:
    def test_groups_by_code(self):
        products = [
            RawProduct(name="Amethyst Bracelet", code="A008", source="stockcheck", quantity=5),
            RawProduct(name="Amethyst Bracelet 8mm", code="A008", source="sales_taka"),
        ]
        result = deduplicate_products(products)
        assert len(result) == 1
        assert result[0].internal_code == "A008"
        assert result[0].qty_on_hand == 5

    def test_groups_by_name_when_no_code(self):
        products = [
            RawProduct(name="Rose Quartz Heart Pendant", source="stockcheck"),
            RawProduct(name="rose quartz heart pendant", source="sales_taka"),
        ]
        result = deduplicate_products(products)
        assert len(result) == 1

    def test_different_codes_stay_separate(self):
        products = [
            RawProduct(name="Bracelet A", code="A001", source="stockcheck"),
            RawProduct(name="Bracelet B", code="A002", source="stockcheck"),
        ]
        result = deduplicate_products(products)
        assert len(result) == 2

    def test_generates_sku_codes(self):
        products = [
            RawProduct(name="Jade Bracelet", code="J001", source="stockcheck"),
        ]
        result = deduplicate_products(products)
        assert result[0].sku_code != ""
        assert result[0].amazon_sku != ""
        assert result[0].nec_plu != ""
        assert result[0].google_product_id != ""

    def test_empty_input(self):
        assert deduplicate_products([]) == []

    def test_skips_short_names(self):
        products = [
            RawProduct(name="AB", source="sales_taka"),
        ]
        result = deduplicate_products(products)
        assert len(result) == 0

    def test_reuses_existing_identifier_assignments(self):
        raw = [
            RawProduct(name="Copper Sculpture", code="A010B", source="stockcheck", quantity=1),
        ]
        existing_assignments = {
            "ba01abb3a168": {
                "sku_code": "VESCUCOPP0000502",
                "nec_plu": generate_nec_plu(502),
            }
        }

        result = deduplicate_products(raw, existing_assignments=existing_assignments)

        assert result[0].sku_code == "VESCUCOPP0000502"
        assert result[0].nec_plu == generate_nec_plu(502)


class TestValidateMasterIdentifiers:
    def test_rejects_misaligned_plu(self):
        product = MasterProduct(
            sku_code="VESCUCOPP0000502",
            nec_plu=generate_nec_plu(503),
        )

        with pytest.raises(ValueError, match="does not align"):
            validate_master_identifiers([product])

    def test_merges_quantities(self):
        products = [
            RawProduct(name="Jade Ring", code="J100", source="stockcheck", quantity=3),
            RawProduct(name="Jade Ring", code="J100", source="stockcheck", quantity=2),
        ]
        result = deduplicate_products(products)
        assert len(result) == 1
        assert result[0].qty_on_hand == 5
