"""Tests for ``app.services.nec_jewel_txt``.

Exercises field encoding rules and replays subsets of the CAG-supplied
sample TXT files (``docs/CAG - NEC Retail POS Onboarding Guides/Import
and Export Sales Interface/SAMPLE .TXT FILES FOR ...``) to assert
byte-equivalent output.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from app.services import nec_jewel_txt as nx


REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = (
    REPO_ROOT
    / "docs"
    / "CAG - NEC Retail POS Onboarding Guides"
    / "Import and Export Sales Interface"
    / "SAMPLE .TXT FILES FOR - SKU, PLU, CATG & PRICE"
)


# ---------------------------------------------------------------------------
# Field encoders
# ---------------------------------------------------------------------------

class TestFieldEncoding:
    def test_plain_strings_are_unquoted(self):
        assert nx.format_field("ROCHER T3 STAR") == "ROCHER T3 STAR"

    def test_field_with_comma_is_double_quoted(self):
        assert nx.format_field("BMX Parts, Accessories") == '"BMX Parts, Accessories"'

    def test_embedded_double_quote_is_doubled(self):
        # Spec example: Coffee Cup 2" → "Coffee Cup 2"" Blue Color"
        assert nx.format_field('Coffee Cup 2" Blue') == '"Coffee Cup 2"" Blue"'

    def test_none_renders_empty(self):
        assert nx.format_field(None) == ""

    def test_money_two_decimals(self):
        assert nx.format_money(10.79) == "10.79"
        assert nx.format_money(0) == "0.00"
        assert nx.format_money(None) == "0.00"
        assert nx.format_money("garbage") == "0.00"

    def test_format_row_terminates_with_crlf(self):
        assert nx.format_row(["A", "B"]) == "A,B\r\n"

    def test_sanitize_strips_forbidden_chars(self):
        assert nx.sanitize_field('Boots, "UGG"') == "Boots; ''UGG''"


# ---------------------------------------------------------------------------
# Filenames
# ---------------------------------------------------------------------------

class TestFilenames:
    def test_catg_pattern(self):
        ts = datetime(2023, 10, 30, 19, 22, 1)
        assert nx.filename_catg("200151", ts) == "CATG_200151_20231030192201.txt"

    def test_sku_pattern_uses_store_id(self):
        ts = datetime(2023, 12, 10, 18, 1, 1)
        assert nx.filename_sku("10026", ts) == "SKU_10026_20231210180101.txt"

    def test_price_pattern_uses_tenant(self):
        ts = datetime(2023, 11, 28, 18, 24, 2)
        assert nx.filename_price("200151", ts) == "PRICE_200151_20231128182402.txt"


# ---------------------------------------------------------------------------
# CATG
# ---------------------------------------------------------------------------

class TestCATG:
    def test_simple_tree_round_trip(self):
        out = nx.write_catg([
            ("200151", "1", "GROCERY", ""),
            ("1", "101", "STAPLES/BASIC MEALS", ""),
            ("101", "10101", "RICE", ""),
        ])
        assert out == (
            "200151,1,GROCERY,\r\n"
            "1,101,STAPLES/BASIC MEALS,\r\n"
            "101,10101,RICE,\r\n"
        )

    def test_field_with_comma_is_quoted(self):
        out = nx.write_catg([("1.1.1BMX", "X", "BMX Parts, Accessories", "OTHER ACCESSORIES")])
        assert out == '1.1.1BMX,X,"BMX Parts, Accessories",OTHER ACCESSORIES\r\n'

    def test_missing_mandatory_raises(self):
        with pytest.raises(ValueError):
            nx.write_catg([("200151", "", "GROCERY", "")])

    @pytest.mark.skipif(not SAMPLE_DIR.exists(), reason="CAG sample dir not present")
    def test_matches_sample_first_lines(self):
        sample = (SAMPLE_DIR / "CATG_200151_20231030192201.txt").read_bytes()
        first = sample.split(b"\r\n", 3)[:3]
        # First three lines of the supplied sample.
        rebuilt = nx.write_catg([
            ("200151", "1", "GROCERY", ""),
            ("1", "101", "STAPLES/BASIC MEALS", ""),
            ("101", "10101", "RICE", ""),
        ]).encode("ascii")
        assert rebuilt.split(b"\r\n", 3)[:3] == first


# ---------------------------------------------------------------------------
# PLU
# ---------------------------------------------------------------------------

class TestPLU:
    def test_basic_row(self):
        out = nx.write_plu([
            nx.plu_row(mode="E", plu_code="29300617072380", sku_code="5087310"),
            nx.plu_row(mode="D", plu_code="4894514071641", sku_code="5107291"),
        ])
        assert out == ",E,29300617072380,5087310\r\n,D,4894514071641,5107291\r\n"

    def test_invalid_mode(self):
        with pytest.raises(ValueError):
            nx.plu_row(mode="X", plu_code="123", sku_code="ABC")

    @pytest.mark.skipif(not SAMPLE_DIR.exists(), reason="CAG sample dir not present")
    def test_matches_sample_byte_for_byte(self):
        sample = (SAMPLE_DIR / "PLU_200151_20231210175301.txt").read_bytes().decode("ascii")
        rows = []
        for line in sample.split("\r\n"):
            if not line:
                continue
            parts = line.split(",")
            assert parts[0] == ""  # FILENAME column always empty per spec
            rows.append(nx.plu_row(mode=parts[1], plu_code=parts[2], sku_code=parts[3]))
        assert nx.write_plu(rows) == sample


# ---------------------------------------------------------------------------
# PRICE
# ---------------------------------------------------------------------------

class TestPRICE:
    def test_basic_row(self):
        out = nx.write_price([
            nx.price_row(
                mode="A",
                sku_code="10001",
                price_incl_tax=13.05,
                price_excl_tax=12.20,
                price_frdate="20190701",
                price_todate="20991231",
            ),
        ])
        assert out == "A,10001,,13.05,12.20,1,20190701,20991231\r\n"

    def test_far_future_default(self):
        row = nx.price_row(
            mode="A",
            sku_code="X1",
            price_incl_tax=1.0,
            price_excl_tax=1.0,
            price_frdate=date(2024, 1, 1),
        )
        assert row[-1] == "20991231"

    def test_derive_excl_tax_round_trip(self):
        # Taxable store at 9% GST: 109.00 incl ⇒ 100.00 excl.
        assert nx.derive_excl_tax(109.0, taxable=True) == 100.0
        # Airside (non-taxable): incl == excl.
        assert nx.derive_excl_tax(50.0, taxable=False) == 50.0

    @pytest.mark.skipif(not SAMPLE_DIR.exists(), reason="CAG sample dir not present")
    def test_matches_sample_first_line(self):
        sample = (SAMPLE_DIR / "PRICE_200151_20231128182402.txt").read_bytes().decode("ascii")
        first_line = sample.split("\r\n", 1)[0]
        # b'D,5003154,10026,0.00,10.79,,20221209,20991231'
        rebuilt = nx.write_price([
            nx.price_row(
                mode="D",
                sku_code="5003154",
                store_id="10026",
                price_incl_tax=0.0,
                price_excl_tax=10.79,
                price_unit=0,  # blank in sample
                price_frdate="20221209",
                price_todate="20991231",
            ),
        ])
        assert rebuilt.rstrip("\r\n") == first_line


# ---------------------------------------------------------------------------
# INVDETAILS
# ---------------------------------------------------------------------------

class TestINVDETAILS:
    def test_update_action(self):
        out = nx.write_invdetails([
            nx.invdetails_row(sku_code="10001", action="Update", inv_value=10),
        ])
        assert out == ",10001,Update,10\r\n"

    def test_invalid_action_rejected(self):
        with pytest.raises(ValueError):
            nx.invdetails_row(sku_code="10001", action="A", inv_value=5)

    def test_negative_qty_rejected(self):
        with pytest.raises(ValueError):
            nx.invdetails_row(sku_code="10001", action="Update", inv_value=-1)


# ---------------------------------------------------------------------------
# PROMO
# ---------------------------------------------------------------------------

class TestPROMO:
    def test_simple_discount(self):
        out = nx.write_promo([
            nx.promo_row(
                disc_id="SD0001",
                line_type="Include",
                disc_method="PercentOff",
                disc_value=10,
                sku_code="10001",
            ),
        ])
        assert out == "SD0001,,10001,Include,PercentOff,10.00,\r\n"

    def test_mix_and_match(self):
        out = nx.write_promo([
            nx.promo_row(
                disc_id="MM0001",
                tenant_catg_code="TOPS",
                line_type="Include",
                disc_method="",
                disc_value=0,
                mm_linegrp="A",
            ),
        ])
        assert out == "MM0001,TOPS,,Include,,0.00,A\r\n"

    def test_requires_sku_or_category(self):
        with pytest.raises(ValueError):
            nx.promo_row(
                disc_id="SD0001",
                line_type="Include",
                disc_method="PercentOff",
                disc_value=10,
            )


# ---------------------------------------------------------------------------
# SKU
# ---------------------------------------------------------------------------

class TestSKU:
    def _kw(self, **over):
        base = dict(
            mode="A",
            sku_code="10001",
            sku_desc="BMXHelmet",
            cost_price=100,
            sku_catg_tenant="1.1.1.1BMXHelmet",
            tax_code="G",
            item_attrib1_brand="BMX",
            item_attrib3_age_group="ALL",
            item_attrib4_changi_collection="NA",
            sku_long_desc="BMX Helmet",
            use_stock=True,
            block_sales=False,
            open_item=False,
            sku_disc=True,
        )
        base.update(over)
        return base

    def test_50_columns(self):
        row = nx.sku_row(**self._kw())
        assert len(row) == 50

    def test_truncation(self):
        long_desc = "X" * 100
        row = nx.sku_row(**self._kw(sku_desc=long_desc))
        assert row[3] == "X" * 60

    def test_invalid_tax_code(self):
        with pytest.raises(ValueError):
            nx.sku_row(**self._kw(tax_code="Z"))

    def test_invalid_mode(self):
        with pytest.raises(ValueError):
            nx.sku_row(**self._kw(mode="Q"))

    def test_round_trip_serialises_with_crlf(self):
        row = nx.sku_row(**self._kw())
        out = nx.write_sku([row])
        assert out.endswith("\r\n")
        assert out.count(",") >= 49  # 50 fields ⇒ 49 separators
