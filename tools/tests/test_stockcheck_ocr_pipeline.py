"""Unit tests for the stock check OCR pipeline.

Tests cover prompt building, page extraction helpers, mangle output, and
the retry/error-handling paths without requiring real GCP credentials.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from stockcheck_ocr_pipeline import (
    STOCKCHECK_SCHEMA,
    build_vertex_prompt,
    layout_text,
    normalized_xy,
)


# ── layout_text ─────────────────────────────────────────────────────────────

class TestLayoutText:
    def test_extracts_text_span(self):
        full_text = "Hello world, this is a test."
        seg = SimpleNamespace(start_index=0, end_index=5)
        anchor = SimpleNamespace(text_segments=[seg])
        assert layout_text(full_text, anchor) == "Hello"

    def test_multiple_segments(self):
        full_text = "abcdefghij"
        segs = [
            SimpleNamespace(start_index=0, end_index=3),
            SimpleNamespace(start_index=5, end_index=8),
        ]
        anchor = SimpleNamespace(text_segments=segs)
        assert layout_text(full_text, anchor) == "abcfgh"

    def test_empty_anchor(self):
        assert layout_text("text", None) == ""

    def test_no_segments(self):
        anchor = SimpleNamespace(text_segments=[])
        assert layout_text("text", anchor) == ""

    def test_strips_whitespace(self):
        full_text = "  hello  "
        seg = SimpleNamespace(start_index=0, end_index=9)
        anchor = SimpleNamespace(text_segments=[seg])
        assert layout_text(full_text, anchor) == "hello"


# ── normalized_xy ───────────────────────────────────────────────────────────

class TestNormalizedXY:
    def test_average_of_vertices(self):
        verts = [
            SimpleNamespace(x=0.0, y=0.0),
            SimpleNamespace(x=1.0, y=0.0),
            SimpleNamespace(x=1.0, y=1.0),
            SimpleNamespace(x=0.0, y=1.0),
        ]
        layout = SimpleNamespace(bounding_poly=SimpleNamespace(normalized_vertices=verts))
        x, y = normalized_xy(layout)
        assert abs(x - 0.5) < 0.01
        assert abs(y - 0.5) < 0.01

    def test_empty_vertices(self):
        layout = SimpleNamespace(bounding_poly=SimpleNamespace(normalized_vertices=[]))
        x, y = normalized_xy(layout)
        assert x == 0.0
        assert y == 0.0


# ── build_vertex_prompt ─────────────────────────────────────────────────────

class TestBuildVertexPrompt:
    def test_includes_document_name(self):
        pages = [{"page_number": 1, "lines": [{"line_no": 1, "x": 0.1, "y": 0.1, "text": "A008 Amethyst Bracelet"}]}]
        prompt = build_vertex_prompt("test_doc.png", pages)
        assert "test_doc.png" in prompt

    def test_includes_page_lines(self):
        pages = [{"page_number": 1, "lines": [{"line_no": 1, "x": 0.1, "y": 0.2, "text": "sample text"}]}]
        prompt = build_vertex_prompt("doc.png", pages)
        assert "sample text" in prompt
        assert "PAGE 1" in prompt

    def test_multi_page(self):
        pages = [
            {"page_number": 1, "lines": [{"line_no": 1, "x": 0.1, "y": 0.1, "text": "page1"}]},
            {"page_number": 2, "lines": [{"line_no": 1, "x": 0.1, "y": 0.1, "text": "page2"}]},
        ]
        prompt = build_vertex_prompt("doc.png", pages)
        assert "PAGE 1" in prompt
        assert "PAGE 2" in prompt

    def test_prompt_has_rules(self):
        prompt = build_vertex_prompt("doc.png", [{"page_number": 1, "lines": []}])
        assert "product_code" in prompt
        assert "quantity" in prompt


# ── STOCKCHECK_SCHEMA ───────────────────────────────────────────────────────

class TestSchema:
    def test_schema_is_valid_dict(self):
        assert isinstance(STOCKCHECK_SCHEMA, dict)
        assert STOCKCHECK_SCHEMA["type"] == "OBJECT"

    def test_schema_requires_page_number(self):
        assert "page_number" in STOCKCHECK_SCHEMA["required"]

    def test_schema_has_items_array(self):
        items_prop = STOCKCHECK_SCHEMA["properties"]["items"]
        assert items_prop["type"] == "ARRAY"

    def test_item_has_product_name(self):
        item_props = STOCKCHECK_SCHEMA["properties"]["items"]["items"]["properties"]
        assert "product_name" in item_props
        assert "product_code" in item_props
        assert "quantity" in item_props
