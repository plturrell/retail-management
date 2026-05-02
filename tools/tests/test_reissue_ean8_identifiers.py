"""Tests for the EAN-8 wipe-and-reissue migration tool.

Covers pin-file parsing, pin resolution + collision rules, plan
determinism, and the output diff/apply behaviour. Does **not** touch the
real master JSON — every test builds its own fixture in a tmp dir.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from reissue_ean8_identifiers import (  # noqa: E402
    Pin,
    apply_plan,
    build_reissue_plan,
    load_pins,
    main,
    resolve_pins,
)


def _product(
    *,
    sku_code: str,
    nec_plu: str,
    internal_code: str | None = None,
    product_type: str = "Bowl",
    material: str = "Amethyst",
    description: str = "",
) -> dict:
    return {
        "sku_code": sku_code,
        "nec_plu": nec_plu,
        "internal_code": internal_code,
        "product_type": product_type,
        "material": material,
        "description": description,
        # google_product_id is regenerated; include it to verify rewrite.
        "google_product_id": f"online:en:SG:{sku_code}",
    }


# ── load_pins ────────────────────────────────────────────────────────────────


class TestLoadPins:
    def test_returns_empty_when_file_omitted(self):
        assert load_pins(None) == []

    def test_missing_file_exits(self, tmp_path):
        with pytest.raises(SystemExit, match="Pin file not found"):
            load_pins(tmp_path / "nope.csv")

    def test_parses_well_formed_csv(self, tmp_path):
        path = tmp_path / "pins.csv"
        path.write_text(
            "match_field,match_value,seq\n"
            "internal_code,H001,1\n"
            "sku_code,VEBWLAMET0000062,2\n"
        )
        assert load_pins(path) == [
            Pin("internal_code", "H001", 1),
            Pin("sku_code", "VEBWLAMET0000062", 2),
        ]

    def test_rejects_unknown_match_field(self, tmp_path):
        path = tmp_path / "pins.csv"
        path.write_text("match_field,match_value,seq\nname,Foo,1\n")
        with pytest.raises(SystemExit, match="match_field must be one of"):
            load_pins(path)

    def test_rejects_seq_out_of_range(self, tmp_path):
        path = tmp_path / "pins.csv"
        path.write_text("match_field,match_value,seq\ninternal_code,H001,0\n")
        with pytest.raises(SystemExit, match="out of range"):
            load_pins(path)

    def test_rejects_non_integer_seq(self, tmp_path):
        path = tmp_path / "pins.csv"
        path.write_text("match_field,match_value,seq\ninternal_code,H001,abc\n")
        with pytest.raises(SystemExit, match="not an integer"):
            load_pins(path)

    def test_rejects_missing_columns(self, tmp_path):
        path = tmp_path / "pins.csv"
        path.write_text("match_field,seq\ninternal_code,1\n")
        with pytest.raises(SystemExit, match="must have columns"):
            load_pins(path)


# ── resolve_pins ─────────────────────────────────────────────────────────────


class TestResolvePins:
    def test_resolves_single_match(self):
        products = [
            _product(sku_code="A", nec_plu="X", internal_code="H001"),
            _product(sku_code="B", nec_plu="Y", internal_code="H002"),
        ]
        result = resolve_pins([Pin("internal_code", "H002", 5)], products)
        assert result == {1: 5}

    def test_rejects_zero_matches(self):
        products = [_product(sku_code="A", nec_plu="X", internal_code="H001")]
        with pytest.raises(SystemExit, match="matched no products"):
            resolve_pins([Pin("internal_code", "MISSING", 1)], products)

    def test_rejects_duplicate_matches(self):
        products = [
            _product(sku_code="A", nec_plu="X", internal_code="DUPE"),
            _product(sku_code="B", nec_plu="Y", internal_code="DUPE"),
        ]
        with pytest.raises(SystemExit, match="matched 2 products"):
            resolve_pins([Pin("internal_code", "DUPE", 1)], products)

    def test_rejects_two_pins_claiming_same_seq(self):
        products = [
            _product(sku_code="A", nec_plu="X", internal_code="H001"),
            _product(sku_code="B", nec_plu="Y", internal_code="H002"),
        ]
        with pytest.raises(SystemExit, match="claim seq=1"):
            resolve_pins(
                [Pin("internal_code", "H001", 1), Pin("internal_code", "H002", 1)],
                products,
            )

    def test_rejects_two_pins_claiming_same_product(self):
        products = [
            _product(sku_code="A", nec_plu="X", internal_code="H001"),
        ]
        with pytest.raises(SystemExit, match="same product"):
            resolve_pins(
                [
                    Pin("internal_code", "H001", 1),
                    Pin("sku_code", "A", 2),
                ],
                products,
            )


# ── build_reissue_plan ───────────────────────────────────────────────────────


class TestBuildReissuePlan:
    def test_no_pins_assigns_seq_one_two_three(self):
        products = [
            _product(sku_code="OLD1", nec_plu="20000000000?", product_type="Bowl", material="Amethyst"),
            _product(sku_code="OLD2", nec_plu="20000000000?", product_type="Bowl", material="Amethyst"),
            _product(sku_code="OLD3", nec_plu="20000000000?", product_type="Bowl", material="Amethyst"),
        ]
        plan = build_reissue_plan(products, {})
        assert [r.new_seq for r in plan] == [1, 2, 3]
        # Each new SKU encodes its seq + (type, material) abbreviations.
        assert plan[0].new_sku_code == "VEBWLAMET0000001"
        assert plan[2].new_sku_code == "VEBWLAMET0000003"
        # Each new PLU is the EAN-8 form of the seq.
        assert plan[0].new_nec_plu == "20000011"

    def test_pinned_seqs_skipped_for_others(self):
        # Three products. Pin product[1] to seq=1. Product[0] should land
        # on seq=2 (1 is taken), product[2] on seq=3.
        products = [
            _product(sku_code="A", nec_plu="X", internal_code="H100"),
            _product(sku_code="B", nec_plu="Y", internal_code="H001"),
            _product(sku_code="C", nec_plu="Z", internal_code="H200"),
        ]
        plan = build_reissue_plan(products, {1: 1})
        seqs = {r.index: r.new_seq for r in plan}
        assert seqs == {0: 2, 1: 1, 2: 3}
        # pinned flag is set only on the pinned row
        assert [r.pinned for r in plan] == [False, True, False]

    def test_pin_to_high_seq_keeps_others_at_low(self):
        # Pin product[0] to seq=99. Products[1] and [2] should still get
        # 1 and 2 — the auto-allocator only skips reserved seqs, doesn't
        # jump past them.
        products = [
            _product(sku_code="A", nec_plu="X"),
            _product(sku_code="B", nec_plu="Y"),
            _product(sku_code="C", nec_plu="Z"),
        ]
        plan = build_reissue_plan(products, {0: 99})
        seqs = {r.index: r.new_seq for r in plan}
        assert seqs == {0: 99, 1: 1, 2: 2}

    def test_thirteen_pins_for_hengwei_scenario(self):
        # The actual user case: pin products at indices 50..62 to seqs 1..13.
        # Remaining 50 products at indices 0..49 should get seqs 14..63.
        products = [_product(sku_code=f"S{i}", nec_plu=f"P{i}") for i in range(70)]
        pin_map = {50 + n: n + 1 for n in range(13)}
        plan = build_reissue_plan(products, pin_map)
        # Pinned 13 land on 1..13.
        for n in range(13):
            assert plan[50 + n].new_seq == n + 1
        # The very first non-pinned product gets seq 14.
        assert plan[0].new_seq == 14
        # All seqs unique.
        assert len({r.new_seq for r in plan}) == len(products)

    def test_deterministic_re_run(self):
        products = [
            _product(sku_code=f"S{i}", nec_plu=f"P{i}", internal_code=f"H{i:03d}")
            for i in range(20)
        ]
        plan_a = build_reissue_plan(products, {5: 1, 10: 2})
        plan_b = build_reissue_plan(products, {5: 1, 10: 2})
        assert [(r.index, r.new_seq) for r in plan_a] == [
            (r.index, r.new_seq) for r in plan_b
        ]


# ── apply_plan ───────────────────────────────────────────────────────────────


class TestApplyPlan:
    def test_rewrites_sku_plu_and_google_id(self):
        products = [_product(sku_code="OLD", nec_plu="OLD-PLU")]
        plan = build_reissue_plan(products, {})
        apply_plan(plan)
        p = products[0]
        assert p["sku_code"] == "VEBWLAMET0000001"
        assert p["nec_plu"] == "20000011"
        assert p["google_product_id"] == "online:en:SG:VEBWLAMET0000001"


# ── End-to-end through main() ────────────────────────────────────────────────


def _write_master(path: Path, products: list[dict]) -> None:
    payload = {
        "generated_at": "2026-01-01",
        "total_products": len(products),
        "summary": {},
        "products": products,
        "metadata": {},
    }
    path.write_text(json.dumps(payload, indent=2))


class TestMainCli:
    def test_dry_run_writes_diff_only(self, tmp_path, capsys):
        master = tmp_path / "master.json"
        diff = tmp_path / "diff.csv"
        _write_master(
            master,
            [_product(sku_code="LEGACY", nec_plu="2000000000626", internal_code="A448")],
        )
        before = master.read_text()
        rc = main(["--master", str(master), "--diff-csv", str(diff)])
        assert rc == 0
        # Master untouched on dry-run.
        assert master.read_text() == before
        # Diff CSV exists with one data row.
        with diff.open() as h:
            rows = list(csv.DictReader(h))
        assert len(rows) == 1
        assert rows[0]["sku_code_old"] == "LEGACY"
        assert rows[0]["sku_code_new"] == "VEBWLAMET0000001"
        assert rows[0]["nec_plu_new"] == "20000011"
        captured = capsys.readouterr().out
        assert "Dry-run only" in captured

    def test_apply_writes_master_and_backup(self, tmp_path):
        master = tmp_path / "master.json"
        diff = tmp_path / "diff.csv"
        _write_master(
            master,
            [_product(sku_code="LEGACY", nec_plu="2000000000626")],
        )
        rc = main(
            ["--master", str(master), "--diff-csv", str(diff), "--apply"]
        )
        assert rc == 0
        # Master was rewritten with the new identifiers.
        rewritten = json.loads(master.read_text())
        assert rewritten["products"][0]["sku_code"] == "VEBWLAMET0000001"
        assert rewritten["products"][0]["nec_plu"] == "20000011"
        # Backup file exists alongside the master.
        backups = list(tmp_path.glob("master.*.bak.json"))
        assert len(backups) == 1, f"expected one backup, got {backups}"

    def test_apply_with_pin_file_honours_pinned_seq(self, tmp_path):
        master = tmp_path / "master.json"
        diff = tmp_path / "diff.csv"
        pins = tmp_path / "pins.csv"
        _write_master(
            master,
            [
                _product(sku_code="A", nec_plu="X", internal_code="OTHER"),
                _product(sku_code="B", nec_plu="Y", internal_code="HENGWEI001"),
            ],
        )
        pins.write_text(
            "match_field,match_value,seq\ninternal_code,HENGWEI001,1\n"
        )
        rc = main(
            [
                "--master", str(master),
                "--pin-file", str(pins),
                "--diff-csv", str(diff),
                "--apply",
            ]
        )
        assert rc == 0
        data = json.loads(master.read_text())
        # Pinned product (HENGWEI001) gets seq=1.
        hengwei = next(p for p in data["products"] if p["internal_code"] == "HENGWEI001")
        assert hengwei["nec_plu"] == "20000011"  # seq=1
        # Other product gets seq=2 (1 was reserved).
        other = next(p for p in data["products"] if p["internal_code"] == "OTHER")
        assert other["nec_plu"] != hengwei["nec_plu"]
        # Re-derive: seq=2 → "2000002" + check digit
        assert other["nec_plu"].startswith("20000020") or other["nec_plu"][:7] == "2000002"
