"""Client to communicate with the Multica SPCS AI Platform."""
import logging
from typing import Any, Dict, Optional

import httpx
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger("multica.client")


class MulticaResponse(BaseModel):
    model_used: str
    raw_text: str
    payload: Optional[Dict[str, Any]] = None


async def analyze_inventory_health(store_id: str, low_stock_threshold: int = 5) -> MulticaResponse:
    """Trigger the 'Genius' layer analysis on the Multica platform for inventory."""
    # Check if we have an endpoint defined. 
    # This URL should be the SPCS public endpoint from `SHOW ENDPOINTS IN SERVICE multica_service;`
    endpoint = getattr(settings, "MULTICA_ENDPOINT_URL", None)
    
    if not endpoint:
        logger.warning("MULTICA_ENDPOINT_URL not configured. Returning fallback response.")
        return MulticaResponse(
            model_used="fallback",
            raw_text="Multica AI platform endpoint is not hooked up to the backend.",
            payload={"status": "offline", "critical_skus": []}
        )
        
    url = f"{endpoint}/api/v1/analyze/inventory"
    payload = {"store_id": store_id, "low_stock_threshold": low_stock_threshold}
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=45.0)
            resp.raise_for_status()
            data = resp.json()
            return MulticaResponse(**data)
    except Exception as e:
        logger.error("Multica AI connection failed: %s", str(e))
        return MulticaResponse(
            model_used="error",
            raw_text=f"Failed to connect to Multica: {str(e)}",
            payload={"status": "offline", "critical_skus": []}
        )
