"""Async job dispatcher for heavy AI pipelines.

Separates heavy work (OCR, catalog enrichment, embedding generation) from the
HTTP request path. Jobs are dispatched to:
  - Cloud Tasks (production) → routes to a Cloud Run Jobs worker
  - In-process asyncio.create_task (development) → immediate background execution

Each job:
  1. Creates an AIArtifact row with status="pending"
  2. Dispatches the work
  3. Worker updates status to "processing" → "completed" or "failed"
  4. Results are written to payload (JSON) or gcs_uri (large blobs)
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional
from uuid import UUID

from app.config import settings

logger = logging.getLogger("job_dispatcher")

# ── Job types ────────────────────────────────────────────────────

JOB_TYPES = {
    "catalog_enrichment",
    "ocr_receipt",
    "ocr_invoice",
    "ocr_sales_ledger",
    "bulk_pricing_review",
    # NOTE: ``embedding_generation`` was previously listed here but the
    # underlying provider integration was never built. Re-add it (and a
    # corresponding handler in ``_execute_job``) once the embedding
    # service is wired up; until then it is intentionally absent so the
    # dispatcher rejects scheduling attempts up-front.
}

# Cloud Tasks queue (production only)
_TASKS_QUEUE = f"projects/{settings.GCP_PROJECT_ID}/locations/asia-southeast1/queues/ai-jobs"
_WORKER_URL = f"https://retailsg-worker-{settings.GCP_PROJECT_ID.split('-')[0]}.asia-southeast1.run.app"


async def dispatch_job(
    job_type: str,
    store_id: UUID,
    payload: dict[str, Any],
    gcs_input_uri: Optional[str] = None,
) -> str:
    """Create an AI artifact and dispatch the job.

    Returns the artifact_id so the caller can poll for completion.
    """
    if job_type not in JOB_TYPES:
        raise ValueError(f"Unknown job type: {job_type}")

    import uuid as _uuid
    from datetime import datetime, timezone
    from app.firestore_helpers import create_document

    artifact_id = str(_uuid.uuid4())
    now = datetime.now(timezone.utc)
    create_document("ai-artifacts", {
        "store_id": str(store_id),
        "artifact_type": job_type,
        "status": "pending",
        "payload": {"input": payload, "gcs_input_uri": gcs_input_uri},
        "gcs_uri": None,
        "created_at": now,
        "updated_at": now,
    }, doc_id=artifact_id)

    if settings.ENVIRONMENT == "production":
        await _dispatch_cloud_tasks(job_type, artifact_id, payload, gcs_input_uri)
    else:
        asyncio.create_task(_run_local(job_type, artifact_id))

    logger.info("Dispatched job %s artifact=%s", job_type, artifact_id)
    return artifact_id


async def _dispatch_cloud_tasks(
    job_type: str,
    artifact_id: str,
    payload: dict,
    gcs_input_uri: Optional[str],
) -> None:
    """Send a task to Cloud Tasks (production)."""
    try:
        from google.cloud import tasks_v2

        client = tasks_v2.CloudTasksClient()
        task_body = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{_WORKER_URL}/jobs/{job_type}",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(
                    {
                        "artifact_id": artifact_id,
                        "gcs_input_uri": gcs_input_uri,
                        **payload,
                    }
                ).encode(),
                "oidc_token": {
                    "service_account_email": f"retailsg-api@{settings.GCP_PROJECT_ID}.iam.gserviceaccount.com",
                },
            }
        }
        client.create_task(parent=_TASKS_QUEUE, task=task_body)
    except Exception as exc:
        logger.error("Cloud Tasks dispatch failed: %s — falling back to local", exc)
        asyncio.create_task(_run_local(job_type, artifact_id))


async def _run_local(job_type: str, artifact_id: str) -> None:
    """Run job in-process for local development."""
    from app.firestore_helpers import get_document, update_document

    artifact = get_document("ai-artifacts", artifact_id)
    if artifact is None:
        logger.error("Artifact %s not found for local job", artifact_id)
        return

    update_document("ai-artifacts", artifact_id, {"status": "processing"})

    try:
        output = await _execute_job(job_type, artifact.get("payload") or {})
        update_document("ai-artifacts", artifact_id, {
            "status": "completed",
            "payload": {**(artifact.get("payload") or {}), "output": output},
        })
    except Exception as exc:
        update_document("ai-artifacts", artifact_id, {
            "status": "failed",
            "payload": {**(artifact.get("payload") or {}), "error": str(exc)},
        })
        logger.error("Local job %s failed: %s", artifact_id, exc)


async def _execute_job(job_type: str, payload: dict) -> dict:
    """Execute a specific job type. Add new job handlers here."""
    if job_type == "catalog_enrichment":
        return await _job_catalog_enrichment(payload)
    elif job_type in ("ocr_receipt", "ocr_invoice", "ocr_sales_ledger"):
        return await _job_ocr(job_type, payload)
    elif job_type == "bulk_pricing_review":
        return await _job_bulk_pricing(payload)
    else:
        raise ValueError(f"No handler registered for job_type={job_type!r}")


# ── Job implementations ──────────────────────────────────────────

async def _job_catalog_enrichment(payload: dict) -> dict:
    """Enrich SKU catalog with AI-generated descriptions and tags."""
    from app.services.ai_gateway import AIRequest, ASYNC_TIMEOUT_SECONDS, invoke

    sku_data = payload.get("input", {}).get("sku_data", {})
    prompt = f"""Generate a rich product description and 5 search tags for this jewelry item.
SKU: {sku_data.get('sku_code', '')}
Current description: {sku_data.get('description', '')}
Category: {sku_data.get('category', '')}
Brand: {sku_data.get('brand', '')}

Respond as JSON: {{"description": "...", "tags": ["...", "..."]}}"""

    resp = await invoke(
        AIRequest(
            prompt=prompt,
            purpose="catalog_enrichment",
            timeout_seconds=ASYNC_TIMEOUT_SECONDS,
            max_output_tokens=512,
        ),
        fallback_text='{"description": "", "tags": []}',
    )
    return {"enriched_text": resp.text, "request_id": resp.request_id}


async def _job_ocr(job_type: str, payload: dict) -> dict:
    """OCR processing via Document AI, with optional Vertex extraction."""
    from app.services.document_ocr import process_document_from_gcs

    input_payload = payload.get("input", {}) if isinstance(payload.get("input"), dict) else {}
    gcs_uri = payload.get("gcs_input_uri") or input_payload.get("gcs_input_uri") or ""
    logger.info("OCR job %s for %s", job_type, gcs_uri)
    return await process_document_from_gcs(
        job_type=job_type,
        gcs_uri=gcs_uri,
        payload=input_payload,
    )


async def _job_bulk_pricing(payload: dict) -> dict:
    """Bulk pricing review across all SKUs in a store."""
    from app.services.ai_gateway import AIRequest, ASYNC_TIMEOUT_SECONDS, invoke

    store_summary = json.dumps(payload.get("input", {}), default=str)[:4000]
    prompt = f"""Review the pricing of all SKUs in this store and identify opportunities.

STORE DATA:
{store_summary}

Respond as JSON: {{"recommendations": [{{"sku_code": "...", "action": "...", "reason": "..."}}]}}"""

    resp = await invoke(
        AIRequest(
            prompt=prompt,
            purpose="bulk_pricing_review",
            timeout_seconds=ASYNC_TIMEOUT_SECONDS,
            max_output_tokens=2048,
        ),
        fallback_text='{"recommendations": []}',
    )
    return {"result": resp.text, "request_id": resp.request_id}
