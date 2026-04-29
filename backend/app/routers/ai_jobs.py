"""Endpoints for AI background jobs — dispatch and poll."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from google.cloud.firestore_v1.client import Client as FirestoreClient

from app.firestore import get_firestore_db
from app.firestore_helpers import get_document, query_collection
from app.auth.dependencies import RoleEnum, get_current_user, require_store_access, require_store_role
from app.services.job_dispatcher import JOB_TYPES, dispatch_job
from app.services.gcs import upload_bytes

router = APIRouter(prefix="/api/ai", tags=["ai-jobs"])


# ── Dispatch ─────────────────────────────────────────────────────

class JobDispatchRequest(BaseModel):
    job_type: str
    store_id: UUID
    payload: dict = {}
    gcs_input_uri: Optional[str] = None


class JobDispatchResponse(BaseModel):
    artifact_id: str
    status: str


class GCSUploadResponse(BaseModel):
    gcs_uri: str
    content_type: str
    size_bytes: int


_MAX_AI_UPLOAD_BYTES = 25 * 1024 * 1024


@router.post("/jobs", response_model=JobDispatchResponse, status_code=202)
async def create_job(
    body: JobDispatchRequest,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Dispatch an async AI job (OCR, catalog enrichment, etc.)."""
    from app.auth.dependencies import ensure_store_access
    ensure_store_access(user, body.store_id)

    if body.job_type not in JOB_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown job type: {body.job_type}")

    artifact_id = await dispatch_job(
        job_type=body.job_type,
        store_id=body.store_id,
        payload=body.payload,
        gcs_input_uri=body.gcs_input_uri,
    )
    return JobDispatchResponse(artifact_id=artifact_id, status="pending")


@router.post("/jobs/upload", response_model=GCSUploadResponse)
async def upload_job_input(
    store_id: UUID = Form(...),
    artifact_type: str = Form("job-input"),
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Upload a large AI input to GCS and return a gs:// URI for dispatch."""
    from app.auth.dependencies import ensure_store_access

    ensure_store_access(user, store_id)
    raw = await file.read(_MAX_AI_UPLOAD_BYTES + 1)
    if len(raw) > _MAX_AI_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="AI input exceeds 25MB limit")
    if not raw:
        raise HTTPException(status_code=400, detail="AI input is empty")

    safe_name = "".join(
        c if c.isalnum() or c in {".", "-", "_"} else "_"
        for c in (file.filename or "upload")
    ).strip("._") or "upload"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = f"{store_id}/{artifact_type}/{timestamp}-{safe_name}"
    content_type = file.content_type or "application/octet-stream"
    gcs_uri = await upload_bytes(raw, path, content_type)
    return GCSUploadResponse(
        gcs_uri=gcs_uri,
        content_type=content_type,
        size_bytes=len(raw),
    )


# ── Poll ─────────────────────────────────────────────────────────

class ArtifactStatus(BaseModel):
    id: str
    artifact_type: str
    status: str
    payload: Optional[dict] = None
    gcs_uri: Optional[str] = None
    created_at: Optional[str] = None


@router.get("/jobs/{artifact_id}", response_model=ArtifactStatus)
async def get_job_status(
    artifact_id: UUID,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Poll the status of an AI job."""
    artifact = get_document("ai-artifacts", str(artifact_id))
    if artifact is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if artifact.get("store_id") is not None:
        from app.auth.dependencies import ensure_store_access
        ensure_store_access(user, UUID(artifact["store_id"]))

    return ArtifactStatus(
        id=artifact.get("id", str(artifact_id)),
        artifact_type=artifact.get("artifact_type", ""),
        status=artifact.get("status", "unknown"),
        payload=artifact.get("payload"),
        gcs_uri=artifact.get("gcs_uri"),
        created_at=str(artifact.get("created_at")) if artifact.get("created_at") else None,
    )


# ── Cost dashboard ───────────────────────────────────────────────

class CostSummary(BaseModel):
    period: str
    total_invocations: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    by_purpose: dict[str, float]
    fallback_count: int


@router.get("/costs", response_model=CostSummary)
async def ai_cost_summary(
    store_id: Optional[UUID] = None,
    days: int = Query(30, ge=1, le=365),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """AI cost visibility — total tokens, cost, fallback rate."""
    if store_id is not None:
        from app.auth.dependencies import ensure_store_role
        ensure_store_role(user, store_id, RoleEnum.manager)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Query invocations from Firestore
    filters = [("created_at", ">=", cutoff)]
    if store_id:
        filters.append(("store_id", "==", str(store_id)))

    invocations = query_collection("ai-invocations", filters=filters)

    total_in_tokens = 0
    total_out_tokens = 0
    total_cost = 0.0
    fallback_count = 0
    by_purpose: dict[str, float] = {}

    for inv in invocations:
        total_in_tokens += int(inv.get("input_tokens", 0))
        total_out_tokens += int(inv.get("output_tokens", 0))
        cost = float(inv.get("estimated_cost_usd", 0))
        total_cost += cost
        if inv.get("is_fallback"):
            fallback_count += 1
        purpose = inv.get("purpose", "unknown")
        by_purpose[purpose] = by_purpose.get(purpose, 0.0) + cost

    by_purpose = {k: round(v, 4) for k, v in by_purpose.items()}

    return CostSummary(
        period=f"last {days} days",
        total_invocations=len(invocations),
        total_input_tokens=total_in_tokens,
        total_output_tokens=total_out_tokens,
        total_cost_usd=round(total_cost, 4),
        by_purpose=by_purpose,
        fallback_count=fallback_count,
    )
