"""Unit tests for the centralized AI gateway.

All tests mock the Gemini client — no real API calls.
Covers: success path, timeout, API error, cost estimation,
fallback, logging, and persist_invocation.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.services.ai_gateway import (
    AIRequest,
    AIResponse,
    SYNC_TIMEOUT_SECONDS,
    ASYNC_TIMEOUT_SECONDS,
    _estimate_cost,
    invoke,
)


# ── Helpers ──────────────────────────────────────────────────────

@dataclass
class FakeUsageMeta:
    prompt_token_count: int = 100
    candidates_token_count: int = 50


@dataclass
class FakeResponse:
    text: str = '{"result": "ok"}'
    usage_metadata: Optional[FakeUsageMeta] = None

    def __post_init__(self):
        if self.usage_metadata is None:
            self.usage_metadata = FakeUsageMeta()


# ── Cost estimation ──────────────────────────────────────────────

class TestCostEstimation:

    def test_gemini_25_flash_cost(self):
        # 1000 input tokens × $0.15/M + 500 output tokens × $0.60/M
        cost = _estimate_cost("gemini-2.5-flash", 1000, 500)
        expected = (1000 * 0.15 + 500 * 0.60) / 1_000_000
        assert cost == round(expected, 6)

    def test_gemini_20_flash_cost(self):
        cost = _estimate_cost("gemini-2.0-flash", 2000, 1000)
        expected = (2000 * 0.10 + 1000 * 0.40) / 1_000_000
        assert cost == round(expected, 6)

    def test_unknown_model_uses_default(self):
        cost = _estimate_cost("gemini-99-turbo", 1000, 500)
        # Should fall back to gemini-2.5-flash rates
        expected = (1000 * 0.15 + 500 * 0.60) / 1_000_000
        assert cost == round(expected, 6)

    def test_zero_tokens(self):
        assert _estimate_cost("gemini-2.5-flash", 0, 0) == 0.0


# ── Config timeouts ──────────────────────────────────────────────

class TestConfigTimeouts:

    def test_sync_timeout_from_config(self):
        from app.config import settings
        assert SYNC_TIMEOUT_SECONDS == settings.AI_SYNC_TIMEOUT_SECONDS

    def test_async_timeout_from_config(self):
        from app.config import settings
        assert ASYNC_TIMEOUT_SECONDS == settings.AI_ASYNC_TIMEOUT_SECONDS


# ── Invoke success path ─────────────────────────────────────────

class TestInvokeSuccess:

    @pytest.mark.asyncio
    async def test_success_returns_text_and_metadata(self):
        fake_resp = FakeResponse(text='{"price": 42.0}')

        with patch("app.services.ai_gateway._sync_gemini_call", return_value=fake_resp):
            with patch("app.services.ai_gateway.persist_invocation", new_callable=AsyncMock):
                resp = await invoke(AIRequest(prompt="test", purpose="test"))

        assert resp.text == '{"price": 42.0}'
        assert resp.model == "gemini-2.5-flash"
        assert resp.is_fallback is False
        assert resp.error is None
        assert resp.input_tokens == 100
        assert resp.output_tokens == 50
        assert resp.estimated_cost_usd > 0
        assert resp.latency_ms >= 0
        assert len(resp.request_id) == 12

    @pytest.mark.asyncio
    async def test_success_calls_persist(self):
        fake_resp = FakeResponse()
        mock_persist = AsyncMock()

        with patch("app.services.ai_gateway._sync_gemini_call", return_value=fake_resp):
            with patch("app.services.ai_gateway.persist_invocation", mock_persist):
                resp = await invoke(AIRequest(prompt="test"))
                # Let the fire-and-forget task run
                await asyncio.sleep(0.05)

        mock_persist.assert_called_once()
        call_args = mock_persist.call_args
        assert call_args[0][1].request_id == resp.request_id


# ── Invoke timeout path ─────────────────────────────────────────

class TestInvokeTimeout:

    @pytest.mark.asyncio
    async def test_timeout_returns_fallback(self):
        async def slow_call(*args, **kwargs):
            await asyncio.sleep(10)

        with patch("app.services.ai_gateway.asyncio.to_thread", side_effect=slow_call):
            with patch("app.services.ai_gateway.persist_invocation", new_callable=AsyncMock):
                resp = await invoke(
                    AIRequest(prompt="test", timeout_seconds=0.05),
                    fallback_text='{"fallback": true}',
                )

        assert resp.is_fallback is True
        assert resp.text == '{"fallback": true}'
        assert "Timeout" in resp.error

    @pytest.mark.asyncio
    async def test_timeout_still_persists(self):
        async def slow_call(*args, **kwargs):
            await asyncio.sleep(10)

        mock_persist = AsyncMock()

        with patch("app.services.ai_gateway.asyncio.to_thread", side_effect=slow_call):
            with patch("app.services.ai_gateway.persist_invocation", mock_persist):
                await invoke(
                    AIRequest(prompt="test", timeout_seconds=0.05),
                )
                await asyncio.sleep(0.05)

        mock_persist.assert_called_once()
        _, resp = mock_persist.call_args[0]
        assert resp.is_fallback is True


# ── Invoke error path ────────────────────────────────────────────

class TestInvokeError:

    @pytest.mark.asyncio
    async def test_api_error_returns_fallback(self):
        with patch(
            "app.services.ai_gateway._sync_gemini_call",
            side_effect=RuntimeError("API quota exceeded"),
        ):
            with patch("app.services.ai_gateway.persist_invocation", new_callable=AsyncMock):
                resp = await invoke(
                    AIRequest(prompt="test"),
                    fallback_text='{"error": "unavailable"}',
                )

        assert resp.is_fallback is True
        assert resp.text == '{"error": "unavailable"}'
        assert "API quota exceeded" in resp.error

    @pytest.mark.asyncio
    async def test_error_records_latency(self):
        with patch(
            "app.services.ai_gateway._sync_gemini_call",
            side_effect=ConnectionError("network"),
        ):
            with patch("app.services.ai_gateway.persist_invocation", new_callable=AsyncMock):
                resp = await invoke(AIRequest(prompt="test"))

        assert resp.latency_ms >= 0
        assert resp.is_fallback is True


# ── Request ID ───────────────────────────────────────────────────

class TestRequestID:

    def test_auto_generated_request_id(self):
        req = AIRequest(prompt="test")
        assert len(req.request_id) == 12
        # Should be hex
        int(req.request_id, 16)

    def test_custom_request_id(self):
        req = AIRequest(prompt="test", request_id="custom-123")
        assert req.request_id == "custom-123"

    @pytest.mark.asyncio
    async def test_request_id_propagated(self):
        fake_resp = FakeResponse()

        with patch("app.services.ai_gateway._sync_gemini_call", return_value=fake_resp):
            with patch("app.services.ai_gateway.persist_invocation", new_callable=AsyncMock):
                resp = await invoke(
                    AIRequest(prompt="test", request_id="abc123def456"),
                )

        assert resp.request_id == "abc123def456"
