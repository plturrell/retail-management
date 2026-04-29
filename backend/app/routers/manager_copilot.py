from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.dependencies import RoleEnum, can_view_sensitive_operations, get_current_user, require_store_role
from app.schemas.common import DataResponse
from app.schemas.copilot import (
    InventoryAdjustmentHistoryRead,
    InventoryInsightRead,
    ManagerSummaryRead,
    RecommendationApplyRequest,
    RecommendationDecisionRequest,
    RecommendationPublicRead,
    RecommendationStatus,
    RecommendationTriggerRequest,
    RecommendationTriggerResponse,
    RecommendationType,
)
from app.schemas.inventory import InventoryType, SourcingStrategy
from app.services.manager_copilot import (
    apply_recommendation,
    approve_recommendation,
    list_adjustments,
    list_inventory_insights,
    list_recommendations,
    manager_summary,
    redact_inventory_insight_for_role,
    redact_manager_summary_for_role,
    redact_recommendation_for_role,
    reject_recommendation,
    trigger_analysis,
)

router = APIRouter(prefix="/api/stores/{store_id}/copilot", tags=["manager-copilot"])


@router.get("/summary", response_model=DataResponse[ManagerSummaryRead])
async def get_manager_summary(
    store_id: UUID,
    role_assignment: dict = Depends(require_store_role(RoleEnum.manager)),
):
    role = role_assignment.get("role")
    return DataResponse(data=redact_manager_summary_for_role(manager_summary(store_id), role))


@router.get("/inventory", response_model=DataResponse[list[InventoryInsightRead]])
async def get_inventory_insights(
    store_id: UUID,
    search: str | None = Query(None),
    low_stock_only: bool = Query(False),
    anomaly_only: bool = Query(False),
    inventory_type: InventoryType | None = None,
    sourcing_strategy: SourcingStrategy | None = None,
    lookback_days: int = Query(30, ge=7, le=120),
    role_assignment: dict = Depends(require_store_role(RoleEnum.manager)),
):
    role = role_assignment.get("role")
    return DataResponse(
        data=[
            redact_inventory_insight_for_role(item, role)
            for item in list_inventory_insights(
                store_id,
                search=search,
                low_stock_only=low_stock_only,
                anomaly_only=anomaly_only,
                inventory_type=inventory_type,
                sourcing_strategy=sourcing_strategy,
                lookback_days=lookback_days,
            )
        ]
    )


@router.get("/inventory/{sku_id}", response_model=DataResponse[InventoryInsightRead])
async def get_inventory_detail(
    store_id: UUID,
    sku_id: UUID,
    lookback_days: int = Query(30, ge=7, le=120),
    role_assignment: dict = Depends(require_store_role(RoleEnum.manager)),
):
    role = role_assignment.get("role")
    insights = list_inventory_insights(store_id, lookback_days=lookback_days)
    for insight in insights:
        if insight.sku_id == sku_id:
            return DataResponse(data=redact_inventory_insight_for_role(insight, role))
    raise HTTPException(status_code=404, detail="SKU detail not found")


@router.get("/recommendations", response_model=DataResponse[list[RecommendationPublicRead]])
async def get_recommendations(
    store_id: UUID,
    status: RecommendationStatus | None = None,
    recommendation_type: RecommendationType | None = Query(None, alias="type"),
    sku_id: UUID | None = None,
    role_assignment: dict = Depends(require_store_role(RoleEnum.manager)),
):
    role = role_assignment.get("role")
    return DataResponse(
        data=[
            redact_recommendation_for_role(item, role)
            for item in list_recommendations(
                store_id,
                status=status,
                recommendation_type=recommendation_type,
                sku_id=sku_id,
            )
        ]
    )


@router.post("/recommendations/analyze", response_model=DataResponse[RecommendationTriggerResponse])
async def analyze_recommendations(
    store_id: UUID,
    payload: RecommendationTriggerRequest,
    role_assignment: dict = Depends(require_store_role(RoleEnum.manager)),
    user: dict = Depends(get_current_user),
):
    user_id = user.get("id")
    if not isinstance(user_id, UUID):
        raise HTTPException(status_code=400, detail="Current user is missing a UUID id")
    role = role_assignment.get("role")
    response = await trigger_analysis(store_id, user_id, payload)
    return DataResponse(
        data=response.model_copy(
            update={
                "recommendations": [
                    redact_recommendation_for_role(item, role) for item in response.recommendations
                ]
            }
        )
    )


@router.post("/recommendations/{recommendation_id}/approve", response_model=DataResponse[RecommendationPublicRead])
async def approve_recommendation_route(
    store_id: UUID,
    recommendation_id: UUID,
    payload: RecommendationDecisionRequest,
    role_assignment: dict = Depends(require_store_role(RoleEnum.manager)),
    user: dict = Depends(get_current_user),
):
    user_id = user.get("id")
    if not isinstance(user_id, UUID):
        raise HTTPException(status_code=400, detail="Current user is missing a UUID id")
    role = role_assignment.get("role")
    try:
        recommendation = approve_recommendation(store_id, recommendation_id, user_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return DataResponse(data=redact_recommendation_for_role(recommendation, role))


@router.post("/recommendations/{recommendation_id}/reject", response_model=DataResponse[RecommendationPublicRead])
async def reject_recommendation_route(
    store_id: UUID,
    recommendation_id: UUID,
    payload: RecommendationDecisionRequest,
    role_assignment: dict = Depends(require_store_role(RoleEnum.manager)),
    user: dict = Depends(get_current_user),
):
    user_id = user.get("id")
    if not isinstance(user_id, UUID):
        raise HTTPException(status_code=400, detail="Current user is missing a UUID id")
    role = role_assignment.get("role")
    try:
        recommendation = reject_recommendation(store_id, recommendation_id, user_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return DataResponse(data=redact_recommendation_for_role(recommendation, role))


@router.post("/recommendations/{recommendation_id}/apply", response_model=DataResponse[RecommendationPublicRead])
async def apply_recommendation_route(
    store_id: UUID,
    recommendation_id: UUID,
    payload: RecommendationApplyRequest,
    role_assignment: dict = Depends(require_store_role(RoleEnum.manager)),
    user: dict = Depends(get_current_user),
):
    user_id = user.get("id")
    if not isinstance(user_id, UUID):
        raise HTTPException(status_code=400, detail="Current user is missing a UUID id")
    role = role_assignment.get("role")
    existing = next(
        (item for item in list_recommendations(store_id) if item.id == recommendation_id),
        None,
    )
    if existing is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    if (
        not can_view_sensitive_operations(role)
        and existing.workflow_action in {"purchase_order", "work_order", "transfer"}
    ):
        raise HTTPException(
            status_code=403,
            detail="Only owner-director can apply procurement or manufacturing recommendations",
        )
    try:
        recommendation = apply_recommendation(store_id, recommendation_id, user_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return DataResponse(data=redact_recommendation_for_role(recommendation, role))


@router.get("/adjustments", response_model=DataResponse[list[InventoryAdjustmentHistoryRead]])
async def get_adjustment_history(
    store_id: UUID,
    sku_id: UUID | None = None,
    inventory_id: UUID | None = None,
    _: dict = Depends(require_store_role(RoleEnum.manager)),
):
    return DataResponse(
        data=list_adjustments(store_id, sku_id=sku_id, inventory_id=inventory_id)
    )
