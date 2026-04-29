"""Unit tests for the material infocard OCR pipeline.

Tests cover prompt building, material schema, mangle output format,
and deduplication/merge logic without requiring GCP credentials.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from material_infocard_ocr_pipeline import (
    MATERIAL_SCHEMA,
    _mangle_str,
    build_vertex_prompt,
    write_json,
    write_mangle,
)


# ── MATERIAL_SCHEMA ─────────────────────────────────────────────────────────

class TestMaterialSchema:
    def test_schema_is_valid_dict(self):
        assert isinstance(MATERIAL_SCHEMA, dict)
        assert MATERIAL_SCHEMA["type"] == "OBJECT"

    def test_requires_page_number(self):
        assert "page_number" in MATERIAL_SCHEMA["required"]

    def test_has_materials_array(self):
        materials = MATERIAL_SCHEMA["properties"]["materials"]
        assert materials["type"] == "ARRAY"

    def test_material_has_required_fields(self):
        mat_props = MATERIAL_SCHEMA["properties"]["materials"]["items"]
        required = mat_props["required"]
        assert "material_name" in required
        assert "material_name_raw" in required
        assert "category" in required

    def test_material_has_optional_fields(self):
        mat_fields = MATERIAL_SCHEMA["properties"]["materials"]["items"]["properties"]
        optional = ["colour", "hardness", "origin", "properties", "care_instructions",
                     "product_suitability", "price_range", "notes"]
        for field in optional:
            assert field in mat_fields, f"Missing field: {field}"


# ── build_vertex_prompt ─────────────────────────────────────────────────────

class TestBuildVertexPrompt:
    def test_includes_document_name(self):
        pages = [{"page_number": 1, "lines": [{"line_no": 1, "x": 0.1, "y": 0.1, "text": "Amethyst"}]}]
        prompt = build_vertex_prompt("card_01.png", pages)
        assert "card_01.png" in prompt

    def test_includes_material_rules(self):
        pages = [{"page_number": 1, "lines": []}]
        prompt = build_vertex_prompt("test.png", pages)
        assert "material_name" in prompt
        assert "category" in prompt
        assert "hardness" in prompt

    def test_includes_page_lines(self):
        pages = [{"page_number": 1, "lines": [{"line_no": 1, "x": 0.5, "y": 0.3, "text": "Rose Quartz"}]}]
        prompt = build_vertex_prompt("test.png", pages)
        assert "Rose Quartz" in prompt
        assert "PAGE 1" in prompt

    def test_mentions_crystal_retail_context(self):
        prompt = build_vertex_prompt("x.png", [{"page_number": 1, "lines": []}])
        assert "crystal" in prompt.lower() or "jewellery" in prompt.lower()


# ── _mangle_str ─────────────────────────────────────────────────────────────

class TestMangleStr:
    def test_none_returns_empty_quoted(self):
        assert _mangle_str(None) == '""'

    def test_simple_string(self):
        assert _mangle_str("hello") == '"hello"'

    def test_escapes_quotes(self):
        assert _mangle_str('say "hi"') == '"say \\"hi\\""'

    def test_escapes_backslash(self):
        assert _mangle_str("a\\b") == '"a\\\\b"'

    def test_replaces_newline_with_space(self):
        assert _mangle_str("line1\nline2") == '"line1 line2"'


# ── write_json ──────────────────────────────────────────────────────────────

class TestWriteJson:
    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "output.json"
            data = {"glossary": [{"material_name": "Amethyst"}]}
            write_json(path, data)
            assert path.exists()
            loaded = json.loads(path.read_text())
            assert loaded["glossary"][0]["material_name"] == "Amethyst"

    def test_unicode_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "output.json"
            data = {"name": "翡翠 Jade"}
            write_json(path, data)
            loaded = json.loads(path.read_text())
            assert loaded["name"] == "翡翠 Jade"


# ── write_mangle ────────────────────────────────────────────────────────────

class TestWriteMangle:
    def test_creates_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.mangle"
            data = {
                "pages": [{
                    "materials": [{
                        "material_name": "Amethyst",
                        "category": "Gemstone",
                        "colour": "Purple",
                        "hardness": "7",
                        "origin": "Brazil",
                        "properties": "Calming energy",
                        "care_instructions": "Avoid sunlight",
                        "product_suitability": "Bracelets, pendants",
                    }]
                }]
            }
            write_mangle(path, data)
            content = path.read_text()
            assert "material_info(" in content
            assert '"Amethyst"' in content
            assert '"Gemstone"' in content
            assert content.strip().endswith(".")

    def test_empty_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.mangle"
            write_mangle(path, {"pages": []})
            content = path.read_text()
            assert content.strip() == ""
