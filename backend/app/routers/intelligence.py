"""Intelligence & Analytics API.

Endpoints split by engine:
  /api/intelligence/kpi          → Snowflake SQL aggregations
  /api/intelligence/forecast     → Snowflake Cortex FORECAST
  /api/intelligence/anomalies    → Snowflake Cortex ANOMALY_DETECTION
  /api/intelligence/reorder      → Cortex FORECAST + stock rules
  /api/intelligence/customers    → Snowflake SQL customer analytics
  /api/intelligence/narrative    → Google GenAI (Gemini) executive summary
  /api/intelligence/cortex-query → Snowflake Cortex COMPLETE on ad-hoc SQL
  /api/intelligence/expenses/anomalies → Hybrid Cortex + GenAI

  /api/etl/run                   → Trigger nightly batch ETL (Cloud Task)
  /api/etl/status                → Snowflake health + last sync watermarks
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.services import intelligence as intel
from app.services.snowflake_client import snowflake_is_available
from app.services.snowflake_etl import run_nightly_etl
from app.schemas.common import DataResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["intelligence"])

_intel_router = APIRouter(prefix="/intelligence")
_etl_router = APIRouter(prefix="/etl")


# ------------------------------------------------------------------ #
# Request / Response models                                            #
# ------------------------------------------------------------------ #

class KPIRequest(BaseModel):
    store_id: str | None = None
    period_start: date | None = None
    period_end: date | None = None


class ForecastRequest(BaseModel):
    store_id: str | None = None
    sku_id: str | None = None
    horizon_days: int = Field(30, ge=7, le=90)


class AnomalyRequest(BaseModel):
    store_id: str | None = None
    lookback_days: int = Field(90, ge=30, le=365)


class CortexQueryRequest(BaseModel):
    sql: str = Field(..., min_length=10, description="Safe SELECT query to run in Snowflake")
    question: str = Field(..., min_length=5, description="Natural-language question about the result")


class NarrativeRequest(BaseModel):
    store_id: str
    store_name: str
    period_label: str = Field(..., example="April 2026")
    period_start: date | None = None
    period_end: date | None = None


# ------------------------------------------------------------------ #
# Intelligence endpoints                                               #
# ------------------------------------------------------------------ #

@_intel_router.post("/kpi", response_model=DataResponse[dict])
async def kpi_summary(
    payload: KPIRequest,
    _: User = Depends(get_current_user),
):
    """Pull KPI dashboard data from Snowflake (revenue, expenses, purchasing, margin)."""
    try:
        data = await intel.get_kpi_summary(
            store_id=payload.store_id,
            period_start=payload.period_start,
            period_end=payload.period_end,
        )
        return DataResponse(data=data)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@_intel_router.post("/forecast", response_model=DataResponse[list])
async def demand_forecast(
    payload: ForecastRequest,
    _: User = Depends(get_current_user),
):
    """Snowflake Cortex FORECAST — predicted daily sales qty per SKU."""
    try:
        rows = await intel.forecast_demand(
            store_id=payload.store_id,
            sku_id=payload.sku_id,
            horizon_days=payload.horizon_days,
        )
        return DataResponse(data=rows, message=f"Forecast for next {payload.horizon_days} days")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@_intel_router.post("/anomalies", response_model=DataResponse[list])
async def sales_anomalies(
    payload: AnomalyRequest,
    _: User = Depends(get_current_user),
):
    """Snowflake Cortex ANOMALY_DETECTION — unusual spikes or drops in daily revenue."""
    try:
        rows = await intel.detect_sales_anomalies(
            store_id=payload.store_id,
            lookback_days=payload.lookback_days,
        )
        return DataResponse(data=rows, message=f"Anomalies over last {payload.lookback_days} days")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@_intel_router.get("/reorder/{store_id}", response_model=DataResponse[list])
async def reorder_suggestions(
    store_id: str,
    _: User = Depends(get_current_user),
):
    """Inventory reorder suggestions based on Cortex demand forecast + current stock."""
    try:
        suggestions = await intel.get_reorder_suggestions(store_id=store_id)
        return DataResponse(data=suggestions, message=f"{len(suggestions)} items need attention")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@_intel_router.get("/customers", response_model=DataResponse[dict])
async def customer_analytics(
    store_id: str | None = Query(None),
    _: User = Depends(get_current_user),
):
    """Customer LTV, cohort breakdown, and repeat purchase rate from Snowflake."""
    try:
        data = await intel.get_customer_analytics(store_id=store_id)
        return DataResponse(data=data)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@_intel_router.post("/narrative", response_model=DataResponse[dict])
async def strategic_narrative(
    payload: NarrativeRequest,
    _: User = Depends(get_current_user),
):
    """Google GenAI (Gemini) executive narrative built on live Snowflake KPIs."""
    try:
        # First pull KPIs from Snowflake
        kpi_data = await intel.get_kpi_summary(
            store_id=payload.store_id,
            period_start=payload.period_start,
            period_end=payload.period_end,
        )
        # Then narrate with Gemini
        narrative = await intel.generate_strategic_narrative(
            kpi_data=kpi_data,
            period_label=payload.period_label,
            store_name=payload.store_name,
        )
        return DataResponse(data={"kpi": kpi_data, "narrative": narrative})
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@_intel_router.post("/cortex-query", response_model=DataResponse[dict])
async def cortex_query_summary(
    payload: CortexQueryRequest,
    _: User = Depends(get_current_user),
):
    """Run a SELECT query in Snowflake and get a Cortex COMPLETE natural-language summary.

    The SQL must be a safe read-only SELECT. Mutations are rejected.
    """
    normalized = payload.sql.strip().upper()
    if not normalized.startswith("SELECT"):
        raise HTTPException(status_code=400, detail="Only SELECT statements are permitted")
    for blocked in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"):
        if blocked in normalized:
            raise HTTPException(status_code=400, detail=f"Statement contains disallowed keyword: {blocked}")

    try:
        summary = await intel.cortex_summarise_query_result(
            sql=payload.sql,
            question=payload.question,
        )
        return DataResponse(data={"question": payload.question, "summary": summary})
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@_intel_router.get("/expenses/anomalies/{store_id}", response_model=DataResponse[dict])
async def expense_anomalies(
    store_id: str,
    store_name: str = Query(...),
    _: User = Depends(get_current_user),
):
    """Hybrid: Snowflake detects unusual spending; Gemini narrates findings."""
    try:
        result = await intel.analyse_expense_anomalies(
            store_id=store_id,
            store_name=store_name,
        )
        return DataResponse(data=result)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ------------------------------------------------------------------ #
# ETL endpoints                                                        #
# ------------------------------------------------------------------ #

@_etl_router.post("/run", response_model=DataResponse[dict])
async def trigger_etl(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger the nightly PostgreSQL → Snowflake ETL batch job.

    Called by Cloud Scheduler via Cloud Tasks. Can also be called manually
    by an owner/admin to force an immediate sync.
    Returns immediately; ETL runs in the background.
    """
    async def _run():
        try:
            result = await run_nightly_etl(db)
            logger.info("ETL completed: %s", result)
        except Exception as exc:
            logger.error("ETL run failed: %s", exc, exc_info=True)

    background_tasks.add_task(_run)
    return DataResponse(
        data={"status": "running", "triggered_by": str(user.id)},
        message="ETL job started in background",
    )


@_etl_router.get("/status", response_model=DataResponse[dict])
async def etl_status(
    _: User = Depends(get_current_user),
):
    """Return Snowflake connectivity status and last ETL watermarks."""
    available = await snowflake_is_available()
    if not available:
        return DataResponse(
            data={"snowflake_available": False, "watermarks": []},
            message="Snowflake is not reachable",
        )

    from app.services.snowflake_client import get_snowflake
    from app.config import settings

    async with get_snowflake(schema=settings.SNOWFLAKE_ETL_SCHEMA) as sf:
        try:
            watermarks = await sf.fetch(
                f"SELECT TABLE_NAME, LAST_SYNC_AT FROM {settings.SNOWFLAKE_ETL_SCHEMA}.ETL_WATERMARKS ORDER BY TABLE_NAME"
            )
        except Exception:
            watermarks = []

    return DataResponse(
        data={
            "snowflake_available": True,
            "watermarks": watermarks,
        }
    )


# Mount sub-routers
router.include_router(_intel_router)
router.include_router(_etl_router)
