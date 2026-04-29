"""Centralized AI gateway — every Gemini call goes through here.

Responsibilities:
  1. Timeout enforcement (hard per-request ceiling)
  2. Structured logging of prompt / model / version / latency / tokens
  3. Cost estimation (input + output tokens × per-token rate)
  4. Fallback path on timeout or API error
  5. Request-ID propagation for traceability
  6. Persistent audit trail in Cloud SQL (ai_invocations table)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid as uuid_mod
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID

from app.config import settings

logger = logging.getLogger("ai_gateway")

# ── Token pricing (Gemini 2.5 Flash, USD per 1 M tokens) ────────
_PRICING: dict[str, dict[str, float]] = {
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
}

# ── Defaults (read from config, fall back to safe values) ────────
DEFAULT_MODEL = "gemini-2.5-flash"
SYNC_TIMEOUT_SECONDS: int = getattr(settings, "AI_SYNC_TIMEOUT_SECONDS", 15)
ASYNC_TIMEOUT_SECONDS: int = getattr(settings, "AI_ASYNC_TIMEOUT_SECONDS", 120)


# ── Data classes ─────────────────────────────────────────────────

@dataclass
class AIRequest:
    """Immutable descriptor of a single AI invocation."""
    prompt: str
    model: str = DEFAULT_MODEL
    purpose: str = "general"  # "pricing", "analytics_summary", "catalog_enrichment", …
    request_id: str = field(default_factory=lambda: uuid_mod.uuid4().hex[:12])
    timeout_seconds: float = SYNC_TIMEOUT_SECONDS
    temperature: float = 0.3
    max_output_tokens: int = 1024
    store_id: Optional[UUID] = None
    response_mime_type: Optional[str] = None
    response_schema: Optional[Any] = None


@dataclass
class AIResponse:
    """Result of an AI invocation, including observability metadata."""
    text: str
    model: str
    request_id: str
    latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    is_fallback: bool = False
    error: Optional[str] = None


# ── Gateway ──────────────────────────────────────────────────────

async def invoke(
    req: AIRequest,
    fallback_text: str = '{"error": "AI unavailable"}',
) -> AIResponse:
    """Call Gemini with timeout, logging, and cost tracking.

    This is the **only** function that should talk to the Gemini API.
    All sync product features and async pipelines route through here.
    """
    start = time.monotonic()
    try:
        if req.model.startswith("deepseek"):
            call_coro = _call_openai_compatible(req)
        else:
            call_coro = _call_gemini(req)

        text, usage = await asyncio.wait_for(
            call_coro,
            timeout=req.timeout_seconds,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        input_tokens = usage.get("input", 0)
        output_tokens = usage.get("output", 0)
        cost = _estimate_cost(req.model, input_tokens, output_tokens)

        resp = AIResponse(
            text=text,
            model=req.model,
            request_id=req.request_id,
            latency_ms=elapsed_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=cost,
        )
        _log_invocation(req, resp)
        _schedule_persist(req, resp)
        return resp

    except asyncio.TimeoutError:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        resp = AIResponse(
            text=fallback_text,
            model=req.model,
            request_id=req.request_id,
            latency_ms=elapsed_ms,
            is_fallback=True,
            error=f"Timeout after {req.timeout_seconds}s",
        )
        _log_invocation(req, resp)
        _schedule_persist(req, resp)
        return resp

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        resp = AIResponse(
            text=fallback_text,
            model=req.model,
            request_id=req.request_id,
            latency_ms=elapsed_ms,
            is_fallback=True,
            error=str(exc),
        )
        _log_invocation(req, resp)
        _schedule_persist(req, resp)
        return resp


# ── Internals ────────────────────────────────────────────────────

_background_tasks: set[asyncio.Task] = set()


def _schedule_persist(req: AIRequest, resp: AIResponse) -> None:
    """Fire-and-forget with proper error boundary and reference tracking."""
    task = asyncio.create_task(persist_invocation(req, resp))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


_gemini_client = None


def _get_gemini_client():
    """Return a cached genai Client singleton."""
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        from google.genai.types import HttpOptions

        if settings.GEMINI_USE_VERTEX_AI:
            _gemini_client = genai.Client(
                vertexai=True,
                project=settings.GCP_PROJECT_ID,
                location=settings.VERTEX_AI_LOCATION or settings.GCP_LOCATION,
                http_options=HttpOptions(api_version="v1"),
            )
        elif settings.GEMINI_API_KEY:
            _gemini_client = genai.Client(
                api_key=settings.GEMINI_API_KEY,
                http_options=HttpOptions(api_version="v1"),
            )
        else:
            _gemini_client = genai.Client(http_options=HttpOptions(api_version="v1"))
    return _gemini_client


def _sync_gemini_call(
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    response_mime_type: Optional[str],
    response_schema: Optional[Any],
):
    """Blocking Gemini call — meant to run inside asyncio.to_thread()."""
    client = _get_gemini_client()
    config: dict[str, Any] = {
        "temperature": temperature,
        "max_output_tokens": max_tokens,
    }
    if response_mime_type:
        config["response_mime_type"] = response_mime_type
    if response_schema is not None:
        config["response_schema"] = response_schema
    return client.models.generate_content(
        model=model,
        contents=prompt,
        config=config,
    )


async def _call_gemini(req: AIRequest) -> tuple[str, dict[str, int]]:
    """Non-blocking Gemini call.  Returns (text, {input: N, output: N}).

    Runs the synchronous genai SDK in a thread so the event loop is never blocked.
    """
    response = await asyncio.to_thread(
        _sync_gemini_call,
        req.model,
        req.prompt,
        req.temperature,
        req.max_output_tokens,
        req.response_mime_type,
        req.response_schema,
    )
    text = response.text or ""
    # Extract token counts from usage_metadata if available
    usage: dict[str, int] = {}
    meta = getattr(response, "usage_metadata", None)
    if meta:
        usage["input"] = getattr(meta, "prompt_token_count", 0) or 0
        usage["output"] = getattr(meta, "candidates_token_count", 0) or 0
    return text, usage


_openai_client = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com",
        )
    return _openai_client


def _sync_openai_call(
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
):
    client = _get_openai_client()
    return client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )


async def _call_openai_compatible(req: AIRequest) -> tuple[str, dict[str, int]]:
    """Non-blocking OpenAI SDK call for DeepSeek models."""
    response = await asyncio.to_thread(
        _sync_openai_call,
        req.model,
        req.prompt,
        req.temperature,
        req.max_output_tokens,
    )
    text = response.choices[0].message.content or ""
    usage = {}
    if response.usage:
        usage["input"] = getattr(response.usage, "prompt_tokens", 0)
        usage["output"] = getattr(response.usage, "completion_tokens", 0)
    return text, usage


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = _PRICING.get(model, _PRICING[DEFAULT_MODEL])
    cost = (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000
    return round(cost, 6)


def _log_invocation(req: AIRequest, resp: AIResponse) -> None:
    log_data = {
        "request_id": resp.request_id,
        "purpose": req.purpose,
        "model": resp.model,
        "latency_ms": resp.latency_ms,
        "input_tokens": resp.input_tokens,
        "output_tokens": resp.output_tokens,
        "cost_usd": resp.estimated_cost_usd,
        "is_fallback": resp.is_fallback,
    }
    if resp.error:
        log_data["error"] = resp.error
        logger.warning("ai_invocation %s", log_data)
    else:
        logger.info("ai_invocation %s", log_data)


async def persist_invocation(req: AIRequest, resp: AIResponse) -> None:
    """Write invocation audit row to Firestore (fire-and-forget)."""
    try:
        from datetime import datetime, timezone
        from app.firestore_helpers import create_document

        prompt_hash = hashlib.sha256(req.prompt.encode()).hexdigest()[:64]
        create_document("ai-invocations", {
            "request_id": resp.request_id,
            "purpose": req.purpose,
            "model": resp.model,
            "prompt_hash": prompt_hash,
            "input_tokens": resp.input_tokens,
            "output_tokens": resp.output_tokens,
            "latency_ms": resp.latency_ms,
            "estimated_cost_usd": resp.estimated_cost_usd,
            "is_fallback": resp.is_fallback,
            "error": resp.error,
            "store_id": str(req.store_id) if req.store_id else None,
            "created_at": datetime.now(timezone.utc),
        })
    except Exception as exc:
        logger.warning("Failed to persist AI invocation: %s", exc)
