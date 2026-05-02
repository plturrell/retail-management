"""Client to communicate with the Multica SPCS AI Platform.

The Multica platform runs as a Snowflake SPCS service and is reached over
plain HTTPS. It's *external* and SLA-bound, so we wrap it in a tenacity
retry decorator that backs off exponentially on transient failures
(timeouts, 5xx) but bypasses retry on caller errors (4xx) — those won't
get better by retrying.

When the endpoint isn't configured at all, or every retry exhausts, we
return a `MulticaResponse(model_used="fallback"/"error")` rather than
raising. Callers (manager_copilot) treat that as "no critical_skus" and
keep going.
"""
import logging
from typing import Any, Dict, Optional

import httpx
from pydantic import BaseModel
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.constants.thresholds import (
    DEFAULT_LOW_STOCK_THRESHOLD,
    MULTICA_MAX_RETRIES,
    MULTICA_RETRY_MAX_SECONDS,
    MULTICA_RETRY_MIN_SECONDS,
    MULTICA_TIMEOUT_SECONDS,
)

logger = logging.getLogger("multica.client")


class MulticaResponse(BaseModel):
    model_used: str
    raw_text: str
    payload: Optional[Dict[str, Any]] = None


# Errors we *should* retry: network timeouts, connection drops, 5xx.
# httpx maps connection-level failures into ``httpx.TransportError``;
# 5xx server responses surface as ``httpx.HTTPStatusError`` after
# raise_for_status() — we filter on status_code below.
_RETRIABLE_TRANSPORT = (httpx.TransportError, httpx.TimeoutException)


def _is_retriable_status(exc: BaseException) -> bool:
    """Allow retry on 5xx; never retry on 4xx (request-side fault)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, _RETRIABLE_TRANSPORT)


async def analyze_inventory_health(
    store_id: str,
    low_stock_threshold: int = DEFAULT_LOW_STOCK_THRESHOLD,
) -> MulticaResponse:
    """Trigger the 'Genius' layer analysis on the Multica platform for inventory.

    Retries up to ``MULTICA_MAX_RETRIES`` times on timeout / 5xx with
    exponential backoff (``MULTICA_RETRY_MIN_SECONDS`` → ``MULTICA_RETRY_MAX_SECONDS``).
    Falls back to a synthetic offline response if the endpoint isn't
    configured or every retry fails — the caller logs it but keeps the
    request alive so unrelated dashboards don't go dark.
    """
    # Check if we have an endpoint defined.
    # This URL should be the SPCS public endpoint from `SHOW ENDPOINTS IN SERVICE multica_service;`
    endpoint = getattr(settings, "MULTICA_ENDPOINT_URL", None)

    if not endpoint:
        logger.warning("MULTICA_ENDPOINT_URL not configured. Returning fallback response.")
        return MulticaResponse(
            model_used="fallback",
            raw_text="Multica AI platform endpoint is not hooked up to the backend.",
            payload={"status": "offline", "critical_skus": []},
        )

    url = f"{endpoint}/api/v1/analyze/inventory"
    payload = {"store_id": store_id, "low_stock_threshold": low_stock_threshold}

    async def _call() -> MulticaResponse:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=MULTICA_TIMEOUT_SECONDS)
            resp.raise_for_status()
            data = resp.json()
            return MulticaResponse(**data)

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(MULTICA_MAX_RETRIES),
            wait=wait_exponential(min=MULTICA_RETRY_MIN_SECONDS, max=MULTICA_RETRY_MAX_SECONDS),
            retry=retry_if_exception_type(_RETRIABLE_TRANSPORT)
            | retry_if_exception_type(httpx.HTTPStatusError),
            reraise=True,
        ):
            with attempt:
                # Re-check status_code branch: the retry filter accepts all
                # HTTPStatusError, but we don't actually want to retry 4xx.
                # Tenacity offers no built-in "retry only if status>=500"
                # predicate, so we re-raise as a non-HTTPStatusError when the
                # status is 4xx — which short-circuits the retry filter.
                try:
                    return await _call()
                except httpx.HTTPStatusError as exc:
                    if not _is_retriable_status(exc):
                        # Convert to a different exception type so the
                        # outer retry filter doesn't catch it.
                        logger.warning(
                            "Multica returned non-retriable %s: %s",
                            exc.response.status_code,
                            exc,
                        )
                        raise RuntimeError(
                            f"Multica refused request: {exc.response.status_code}"
                        ) from exc
                    logger.info("Multica returned %s; retrying", exc.response.status_code)
                    raise
        # AsyncRetrying always returns or raises — this line is unreachable
        # but mypy/type-checkers want a return path.
        raise RuntimeError("AsyncRetrying exhausted without return")
    except (RetryError, RuntimeError, httpx.HTTPError) as exc:  # pragma: no cover
        logger.error("Multica AI connection failed after retries: %s", exc)
        return MulticaResponse(
            model_used="error",
            raw_text=f"Failed to connect to Multica: {exc}",
            payload={"status": "offline", "critical_skus": []},
        )
