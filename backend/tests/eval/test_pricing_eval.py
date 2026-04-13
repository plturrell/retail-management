"""Evaluation dataset and harness for pricing strategy AI outputs.

Run: pytest tests/eval/pricing_eval.py -v --no-header

Each test case defines:
  - Input context (cost, discount, margin, velocity)
  - Expected constraints on the output (e.g. margin in range, valid action)
  - Quality checks (reasoning is non-empty, discount not absurd)

These tests do NOT call Gemini — they validate the parsing + fallback logic
against canned responses. For live evals, set EVAL_LIVE=1.
"""
from __future__ import annotations

import json
import os

import pytest

from app.services.gemini_strategist import PricingStrategyUpdate, _parse_json_response

# ── Canned Gemini-style responses ────────────────────────────────

EVAL_CASES: list[dict] = [
    {
        "id": "high_margin_stable",
        "input": {
            "store_name": "Victoria Jewels Orchard",
            "current_discount": 0.10,
            "cogs_sgd": 120.0,
            "target_margin": 0.40,
            "sales_velocity": "moderate",
        },
        "canned_response": json.dumps({
            "store_name": "Victoria Jewels Orchard",
            "recommended_discount_rate": 0.10,
            "recommended_margin": 0.40,
            "reasoning": "Current margin is healthy at 40%. Sales velocity is moderate. No change needed.",
            "action": "APPROVE",
        }),
        "checks": {
            "action_in": ["APPROVE", "HOLD"],
            "margin_min": 0.20,
            "margin_max": 0.80,
            "discount_min": 0.0,
            "discount_max": 0.50,
        },
    },
    {
        "id": "thin_margin_high_velocity",
        "input": {
            "store_name": "Victoria Jewels Marina",
            "current_discount": 0.25,
            "cogs_sgd": 200.0,
            "target_margin": 0.15,
            "sales_velocity": "high",
        },
        "canned_response": json.dumps({
            "store_name": "Victoria Jewels Marina",
            "recommended_discount_rate": 0.15,
            "recommended_margin": 0.25,
            "reasoning": "Margin is thin at 15% despite high velocity. Reduce discount to 15% and target 25% margin.",
            "action": "ALERT",
        }),
        "checks": {
            "action_in": ["ALERT", "HOLD"],
            "margin_min": 0.10,
            "margin_max": 0.60,
            "discount_min": 0.0,
            "discount_max": 0.40,
        },
    },
    {
        "id": "markdown_fenced_response",
        "input": {
            "store_name": "Victoria Jewels Changi",
            "current_discount": 0.05,
            "cogs_sgd": 80.0,
            "target_margin": 0.50,
            "sales_velocity": "low",
        },
        "canned_response": '```json\n{"store_name":"Victoria Jewels Changi","recommended_discount_rate":0.12,"recommended_margin":0.45,"reasoning":"Low velocity suggests increasing discount slightly to stimulate demand.","action":"APPROVE"}\n```',
        "checks": {
            "action_in": ["APPROVE", "HOLD", "ALERT"],
            "margin_min": 0.20,
            "margin_max": 0.80,
            "discount_min": 0.0,
            "discount_max": 0.50,
        },
    },
]


class TestPricingParsing:
    """Validate that canned responses are correctly parsed."""

    @pytest.mark.parametrize("case", EVAL_CASES, ids=[c["id"] for c in EVAL_CASES])
    def test_parse_canned_response(self, case: dict) -> None:
        result = _parse_json_response(case["canned_response"])
        update = PricingStrategyUpdate(**result)

        checks = case["checks"]
        assert update.action in checks["action_in"], f"action={update.action}"
        assert checks["margin_min"] <= update.recommended_margin <= checks["margin_max"]
        assert checks["discount_min"] <= update.recommended_discount_rate <= checks["discount_max"]
        assert len(update.reasoning) > 10, "Reasoning too short"
        assert update.store_name == case["input"]["store_name"]


class TestPricingFallback:
    """Validate fallback on malformed input."""

    def test_empty_response(self) -> None:
        with pytest.raises(Exception):
            _parse_json_response("")

    def test_non_json_response(self) -> None:
        with pytest.raises(Exception):
            _parse_json_response("I think you should raise prices.")

    def test_partial_json(self) -> None:
        with pytest.raises(Exception):
            _parse_json_response('{"store_name": "Test"')
