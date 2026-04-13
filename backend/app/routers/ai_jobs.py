"""Endpoints for AI background jobs — dispatch and poll."""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.ai_artifact import AIArtifact, AIInvocation
from app.models.user import RoleEnum, User, UserStoreRole
from app.auth.dependencies import get_current_user, require_store_access, require_store_role
from app.services.job_dispatcher import JOB_TYPES, dispatch_job

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


@router.post("/jobs", response_model=JobDispatchResponse, status_code=202)
async def create_job(
    body: JobDispatchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Poll the status of an AI job."""
    result = await db.execute(
        select(AIArtifact).where(AIArtifact.id == artifact_id)
    )
    artifact = result.scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if artifact.store_id is not None:
        from app.auth.dependencies import ensure_store_access
        ensure_store_access(user, artifact.store_id)

    return ArtifactStatus(
        id=str(artifact.id),
        artifact_type=artifact.artifact_type,
        status=artifact.status,
        payload=artifact.payload,
        gcs_uri=artifact.gcs_uri,
        created_at=str(artifact.created_at) if artifact.created_at else None,
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """AI cost visibility — total tokens, cost, fallback rate."""
    if store_id is not None:
        from app.auth.dependencies import ensure_store_role, RoleEnum as RE
        ensure_store_role(user, store_id, RE.manager)
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Aggregate totals in SQL instead of loading all rows into Python
    totals_q = (
        select(
            func.count(AIInvocation.id).label("cnt"),
            func.coalesce(func.sum(AIInvocation.input_tokens), 0).label("in_tok"),
            func.coalesce(func.sum(AIInvocation.output_tokens), 0).label("out_tok"),
            func.coalesce(func.sum(AIInvocation.estimated_cost_usd), 0).label("cost"),
            func.sum(func.cast(AIInvocation.is_fallback, Integer)).label("fb"),
        )
        .where(AIInvocation.created_at >= cutoff)
    )
    if store_id:
        totals_q = totals_q.where(AIInvocation.store_id == store_id)

    row = (await db.execute(totals_q)).one()

    # Cost breakdown by purpose
    purpose_q = (
        select(
            AIInvocation.purpose,
            func.coalesce(func.sum(AIInvocation.estimated_cost_usd), 0).label("cost"),
        )
        .where(AIInvocation.created_at >= cutoff)
        .group_by(AIInvocation.purpose)
    )
    if store_id:
        purpose_q = purpose_q.where(AIInvocation.store_id == store_id)

    purpose_rows = (await db.execute(purpose_q)).all()
    by_purpose = {r.purpose: round(float(r.cost), 4) for r in purpose_rows}

    return CostSummary(
        period=f"last {days} days",
        total_invocations=int(row.cnt),
        total_input_tokens=int(row.in_tok),
        total_output_tokens=int(row.out_tok),
        total_cost_usd=round(float(row.cost), 4),
        by_purpose=by_purpose,
        fallback_count=int(row.fb or 0),
    )
