from __future__ import annotations

import logging
import uuid as uuid_mod
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import httpx

from app.auth.dependencies import RoleEnum, can_view_sensitive_operations
from app.config import settings
from app.firestore_helpers import create_document, get_document, query_collection, update_document
from app.schemas.copilot import (
    AuditSource,
    InventoryAdjustmentHistoryRead,
    InventoryInsightRead,
    ManagerSummaryRead,
    RecommendationApplyRequest,
    RecommendationDecisionRequest,
    RecommendationOutcomeRead,
    RecommendationPublicRead,
    RecommendationRead,
    RecommendationStatus,
    RecommendationTriggerRequest,
    RecommendationTriggerResponse,
    RecommendationType,
)
from app.schemas.inventory import InventoryType, SourcingStrategy
from app.schemas.supply_chain import (
    PurchaseOrderCreate,
    PurchaseOrderLineCreate,
    StockTransferCreate,
    StockTransferReceiveRequest,
    SupplierCreate,
    WorkOrderCreate,
    WorkOrderType,
)
from app.services.multica_client import analyze_inventory_health
from app.services.supply_chain import (
    PurchaseOrderStatus,
    SupplyActionSource,
    TransferStatus,
    WorkOrderStatus,
    create_supplier,
    create_purchase_order,
    create_stock_transfer,
    create_work_order,
    list_bom_recipes,
    list_purchase_orders,
    list_suppliers,
    list_stage_inventory,
    list_stock_transfers,
    list_work_orders,
    receive_stock_transfer,
    supply_chain_summary,
)

logger = logging.getLogger(__name__)

SENSITIVE_RECOMMENDATION_METRICS = {
    "supplier_name",
    "unit_cost",
    "purchased_qty",
    "purchased_incoming_qty",
    "material_qty",
    "material_incoming_qty",
    "material_allocated_qty",
    "active_work_order_count",
}


def sku_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/inventory"


def stock_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/stock"


def price_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/prices"


def recommendation_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/recommendations"


def adjustment_collection(store_id: UUID) -> str:
    return f"stores/{store_id}/inventory_adjustments"


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _parse_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            return None
    return None


def _recommendation_from_doc(data: dict[str, Any]) -> RecommendationRead:
    return RecommendationRead(
        id=_parse_uuid(data.get("id")) or uuid_mod.uuid4(),
        store_id=_parse_uuid(data.get("store_id")) or uuid_mod.uuid4(),
        sku_id=_parse_uuid(data.get("sku_id")),
        inventory_id=_parse_uuid(data.get("inventory_id")),
        inventory_type=InventoryType(data.get("inventory_type", InventoryType.finished.value)),
        sourcing_strategy=SourcingStrategy(
            data.get("sourcing_strategy", SourcingStrategy.supplier_premade.value)
        ),
        supplier_name=data.get("supplier_name"),
        type=RecommendationType(data.get("type", RecommendationType.stock_anomaly.value)),
        status=RecommendationStatus(data.get("status", RecommendationStatus.pending.value)),
        title=data.get("title", "Recommendation"),
        rationale=data.get("rationale", ""),
        confidence=float(data.get("confidence", 0) or 0),
        supporting_metrics=data.get("supporting_metrics", {}) or {},
        source=AuditSource(data.get("source", AuditSource.system.value)),
        expected_impact=data.get("expected_impact"),
        current_price=data.get("current_price"),
        suggested_price=data.get("suggested_price"),
        suggested_order_qty=data.get("suggested_order_qty"),
        workflow_action=data.get("workflow_action"),
        analysis_status=data.get("analysis_status", "completed"),
        generated_at=_parse_datetime(data.get("generated_at")) or datetime.now(timezone.utc),
        decided_at=_parse_datetime(data.get("decided_at")),
        decided_by=_parse_uuid(data.get("decided_by")),
        applied_at=_parse_datetime(data.get("applied_at")),
        applied_by=_parse_uuid(data.get("applied_by")),
        note=data.get("note"),
        dedupe_key=data.get("dedupe_key"),
        created_at=_parse_datetime(data.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_parse_datetime(data.get("updated_at")),
    )


def _recommendation_public_view(recommendation: RecommendationRead) -> RecommendationPublicRead:
    return RecommendationPublicRead.model_validate(recommendation.model_dump(mode="python"))


def _redact_supporting_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metrics.items()
        if key not in SENSITIVE_RECOMMENDATION_METRICS
    }


def redact_inventory_insight_for_role(
    insight: InventoryInsightRead,
    role: RoleEnum | str | None,
) -> InventoryInsightRead:
    if can_view_sensitive_operations(role):
        return insight
    return insight.model_copy(
        update={
            "supplier_name": None,
            "cost_price": None,
            "purchased_qty": 0,
            "purchased_incoming_qty": 0,
            "material_qty": 0,
            "material_incoming_qty": 0,
            "material_allocated_qty": 0,
            "in_transit_qty": 0,
            "active_work_order_count": 0,
        }
    )


def redact_recommendation_for_role(
    recommendation: RecommendationPublicRead | RecommendationRead,
    role: RoleEnum | str | None,
) -> RecommendationPublicRead:
    public = (
        recommendation
        if isinstance(recommendation, RecommendationPublicRead)
        else _recommendation_public_view(recommendation)
    )
    if can_view_sensitive_operations(role):
        return public
    return public.model_copy(
        update={
            "supplier_name": None,
            "supporting_metrics": _redact_supporting_metrics(public.supporting_metrics),
        }
    )


def redact_manager_summary_for_role(
    summary: ManagerSummaryRead,
    role: RoleEnum | str | None,
) -> ManagerSummaryRead:
    if can_view_sensitive_operations(role):
        return summary
    return summary.model_copy(
        update={
            "open_purchase_orders": 0,
            "active_work_orders": 0,
            "in_transit_transfers": 0,
            "purchased_units": 0,
            "material_units": 0,
        }
    )


def _adjustment_from_doc(data: dict[str, Any]) -> InventoryAdjustmentHistoryRead:
    return InventoryAdjustmentHistoryRead(
        id=_parse_uuid(data.get("id")) or uuid_mod.uuid4(),
        inventory_id=_parse_uuid(data.get("inventory_id")) or uuid_mod.uuid4(),
        sku_id=_parse_uuid(data.get("sku_id")) or uuid_mod.uuid4(),
        store_id=_parse_uuid(data.get("store_id")) or uuid_mod.uuid4(),
        quantity_delta=int(data.get("quantity_delta", 0) or 0),
        resulting_qty=int(data.get("resulting_qty", 0) or 0),
        reason=data.get("reason", ""),
        source=AuditSource(data.get("source", AuditSource.manual.value)),
        created_by=_parse_uuid(data.get("created_by")),
        recommendation_id=_parse_uuid(data.get("recommendation_id")),
        note=data.get("note"),
        created_at=_parse_datetime(data.get("created_at")) or datetime.now(timezone.utc),
    )


def _bucket_start(now: datetime) -> datetime:
    return now.replace(hour=(now.hour // 6) * 6, minute=0, second=0, microsecond=0)


def _latest_price_by_sku(store_id: UUID) -> dict[str, dict[str, Any]]:
    prices = query_collection(price_collection(store_id))
    today = date.today()
    prices_by_sku: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for price in prices:
        sku_id = str(price.get("sku_id", ""))
        prices_by_sku[sku_id].append(price)

    selected: dict[str, dict[str, Any]] = {}
    for sku_id, records in prices_by_sku.items():
        current = []
        future = []
        for record in records:
            valid_from = _parse_date(record.get("valid_from")) or today
            valid_to = _parse_date(record.get("valid_to")) or date(2099, 12, 31)
            target = current if valid_from <= today <= valid_to else future
            target.append(record)

        candidates = current or future
        candidates.sort(
            key=lambda item: (
                _parse_date(item.get("valid_from")) or date.min,
                _parse_datetime(item.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )
        if candidates:
            selected[sku_id] = candidates[0]
    return selected


def _recent_sales_by_sku(store_id: UUID, lookback_days: int) -> dict[str, dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    sales_by_sku: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"recent_sales_qty": 0, "recent_sales_revenue": 0.0, "last_order_at": None}
    )
    orders = query_collection(f"stores/{store_id}/orders", order_by="-order_date")

    for order in orders:
        order_dt = _parse_datetime(order.get("order_date"))
        if order_dt is None or order_dt < cutoff:
            continue
        if order.get("status") == "voided":
            continue
        for item in order.get("items", []):
            sku_id = str(item.get("sku_id", ""))
            if not sku_id:
                continue
            qty = int(item.get("qty", 0) or 0)
            unit_price = float(item.get("unit_price", 0) or 0)
            entry = sales_by_sku[sku_id]
            entry["recent_sales_qty"] += qty
            entry["recent_sales_revenue"] += round(unit_price * qty, 2)
            if entry["last_order_at"] is None or order_dt > entry["last_order_at"]:
                entry["last_order_at"] = order_dt

    return sales_by_sku


def list_inventory_insights(
    store_id: UUID,
    *,
    search: str | None = None,
    low_stock_only: bool = False,
    anomaly_only: bool = False,
    inventory_type: InventoryType | None = None,
    sourcing_strategy: SourcingStrategy | None = None,
    lookback_days: int = 30,
) -> list[InventoryInsightRead]:
    skus = query_collection(sku_collection(store_id))
    inventory_records = query_collection(stock_collection(store_id))
    stage_positions = list_stage_inventory(store_id)
    latest_prices = _latest_price_by_sku(store_id)
    sales_by_sku = _recent_sales_by_sku(store_id, lookback_days=lookback_days)
    pending_recommendations = query_collection(recommendation_collection(store_id))
    active_work_orders = [
        item
        for item in list_work_orders(store_id)
        if item.status in {WorkOrderStatus.scheduled, WorkOrderStatus.in_progress}
    ]
    in_transit_transfers = [
        item for item in list_stock_transfers(store_id) if item.status == TransferStatus.in_transit
    ]

    pending_counts: dict[str, int] = defaultdict(int)
    pending_price_counts: dict[str, int] = defaultdict(int)
    for rec in pending_recommendations:
        if rec.get("status") not in {
            RecommendationStatus.pending.value,
            RecommendationStatus.approved.value,
        }:
            continue
        sku_id = str(rec.get("sku_id", ""))
        if not sku_id:
            continue
        pending_counts[sku_id] += 1
        if rec.get("type") == RecommendationType.price_change.value:
            pending_price_counts[sku_id] += 1

    sku_map = {str(sku.get("id")): sku for sku in skus}
    stock_by_sku = {str(row.get("sku_id")): row for row in inventory_records if row.get("sku_id")}
    stage_by_key = {
        (str(position.sku_id), position.inventory_type): position for position in stage_positions
    }
    active_work_order_counts: dict[str, int] = defaultdict(int)
    for work_order in active_work_orders:
        active_work_order_counts[str(work_order.finished_sku_id)] += 1
    in_transit_qty_by_sku: dict[str, int] = defaultdict(int)
    for transfer in in_transit_transfers:
        in_transit_qty_by_sku[str(transfer.sku_id)] += transfer.quantity

    insights: list[InventoryInsightRead] = []
    search_lower = search.lower() if search else None

    for sku_id, sku in sku_map.items():
        record = stock_by_sku.get(sku_id)
        purchased_stage = stage_by_key.get((sku_id, InventoryType.purchased))
        material_stage = stage_by_key.get((sku_id, InventoryType.material))
        finished_stage = stage_by_key.get((sku_id, InventoryType.finished))

        description = sku.get("description", "")
        sku_code = sku.get("sku_code", "")
        item_inventory_type = InventoryType(
            sku.get("inventory_type", InventoryType.finished.value)
        )
        item_sourcing_strategy = SourcingStrategy(
            sku.get("sourcing_strategy", SourcingStrategy.supplier_premade.value)
        )
        if search_lower and search_lower not in description.lower() and search_lower not in sku_code.lower():
            continue
        if inventory_type is not None and item_inventory_type != inventory_type:
            continue
        if sourcing_strategy is not None and item_sourcing_strategy != sourcing_strategy:
            continue

        purchased_qty = purchased_stage.quantity_on_hand if purchased_stage else 0
        purchased_incoming_qty = purchased_stage.incoming_quantity if purchased_stage else 0
        material_qty = material_stage.quantity_on_hand if material_stage else 0
        material_incoming_qty = material_stage.incoming_quantity if material_stage else 0
        material_allocated_qty = material_stage.allocated_quantity if material_stage else 0
        finished_qty = finished_stage.quantity_on_hand if finished_stage else 0
        finished_allocated_qty = finished_stage.allocated_quantity if finished_stage else 0

        qty_on_hand = finished_qty
        reorder_level = int(record.get("reorder_level", 0) or 0) if record else 0
        reorder_qty = int(record.get("reorder_qty", 0) or 0) if record else 0
        sales_ctx = sales_by_sku.get(sku_id, {})
        recent_sales_qty = int(sales_ctx.get("recent_sales_qty", 0) or 0)
        recent_sales_revenue = float(sales_ctx.get("recent_sales_revenue", 0.0) or 0.0)
        avg_daily_sales = round(recent_sales_qty / lookback_days, 2) if lookback_days else 0
        days_of_cover = None
        if avg_daily_sales > 0:
            days_of_cover = round(qty_on_hand / avg_daily_sales, 1)

        anomaly_flag = False
        anomaly_reason = None
        if qty_on_hand < 0:
            anomaly_flag = True
            anomaly_reason = "Stock is negative in Firestore and needs reconciliation."
        elif qty_on_hand > max(reorder_level * 5, reorder_qty * 4, 20) and recent_sales_qty == 0:
            anomaly_flag = True
            anomaly_reason = "Stock is sitting far above target with no recent movement."
        elif item_sourcing_strategy == SourcingStrategy.supplier_premade and qty_on_hand <= reorder_level and purchased_qty > 0:
            anomaly_flag = True
            anomaly_reason = "Purchased units are waiting upstream while finished store stock is below target."
        elif item_sourcing_strategy in {
            SourcingStrategy.manufactured_standard,
            SourcingStrategy.manufactured_custom,
        } and qty_on_hand <= reorder_level and active_work_order_counts.get(sku_id, 0) == 0:
            anomaly_flag = True
            anomaly_reason = "Manufactured SKU is below target with no active work order covering the gap."

        low_stock = qty_on_hand <= reorder_level
        if not any(
            [
                record is not None,
                purchased_qty,
                purchased_incoming_qty,
                material_qty,
                material_incoming_qty,
                finished_qty,
                recent_sales_qty,
                pending_counts.get(sku_id, 0),
                active_work_order_counts.get(sku_id, 0),
                in_transit_qty_by_sku.get(sku_id, 0),
            ]
        ):
            continue
        if low_stock_only and not low_stock:
            continue
        if anomaly_only and not anomaly_flag:
            continue

        price_doc = latest_prices.get(sku_id, {})
        insights.append(
            InventoryInsightRead(
                inventory_id=_parse_uuid(record.get("id")) if record else None,
                sku_id=_parse_uuid(sku_id) or uuid_mod.uuid4(),
                store_id=store_id,
                sku_code=sku_code,
                description=description,
                long_description=sku.get("long_description"),
                inventory_type=item_inventory_type,
                sourcing_strategy=item_sourcing_strategy,
                supplier_name=sku.get("supplier_name"),
                cost_price=sku.get("cost_price"),
                current_price=price_doc.get("price_incl_tax"),
                current_price_valid_until=_parse_date(price_doc.get("valid_to")),
                purchased_qty=purchased_qty,
                purchased_incoming_qty=purchased_incoming_qty,
                material_qty=material_qty,
                material_incoming_qty=material_incoming_qty,
                material_allocated_qty=material_allocated_qty,
                finished_qty=finished_qty,
                finished_allocated_qty=finished_allocated_qty,
                in_transit_qty=in_transit_qty_by_sku.get(sku_id, 0),
                active_work_order_count=active_work_order_counts.get(sku_id, 0),
                qty_on_hand=qty_on_hand,
                reorder_level=reorder_level,
                reorder_qty=reorder_qty,
                low_stock=low_stock,
                anomaly_flag=anomaly_flag,
                anomaly_reason=anomaly_reason,
                recent_sales_qty=recent_sales_qty,
                recent_sales_revenue=round(recent_sales_revenue, 2),
                avg_daily_sales=avg_daily_sales,
                days_of_cover=days_of_cover,
                pending_recommendation_count=pending_counts.get(sku_id, 0),
                pending_price_recommendation_count=pending_price_counts.get(sku_id, 0),
                last_updated=(
                    finished_stage.updated_at
                    if finished_stage
                    else (
                        _parse_datetime(record.get("last_updated")) or _parse_datetime(record.get("updated_at"))
                        if record
                        else None
                    )
                ),
            )
        )

    insights.sort(key=lambda item: (not item.low_stock, not item.anomaly_flag, item.sku_code))
    return insights


def list_recommendations(
    store_id: UUID,
    *,
    status: RecommendationStatus | None = None,
    recommendation_type: RecommendationType | None = None,
    sku_id: UUID | None = None,
) -> list[RecommendationRead]:
    docs = query_collection(recommendation_collection(store_id), order_by="-generated_at")
    recommendations = [_recommendation_from_doc(doc) for doc in docs]

    if status is not None:
        recommendations = [rec for rec in recommendations if rec.status == status]
    if recommendation_type is not None:
        recommendations = [rec for rec in recommendations if rec.type == recommendation_type]
    if sku_id is not None:
        recommendations = [rec for rec in recommendations if rec.sku_id == sku_id]
    return recommendations


def list_adjustments(
    store_id: UUID,
    *,
    sku_id: UUID | None = None,
    inventory_id: UUID | None = None,
) -> list[InventoryAdjustmentHistoryRead]:
    docs = query_collection(adjustment_collection(store_id), order_by="-created_at")
    rows = [_adjustment_from_doc(doc) for doc in docs]
    if sku_id is not None:
        rows = [row for row in rows if row.sku_id == sku_id]
    if inventory_id is not None:
        rows = [row for row in rows if row.inventory_id == inventory_id]
    return rows


def manager_summary(store_id: UUID) -> ManagerSummaryRead:
    recommendations = list_recommendations(store_id)
    insights = list_inventory_insights(store_id)
    supply_summary = supply_chain_summary(store_id)

    pending = [rec for rec in recommendations if rec.status in {RecommendationStatus.pending, RecommendationStatus.approved}]
    recent_outcomes = [
        RecommendationOutcomeRead(
            recommendation_id=rec.id,
            sku_id=rec.sku_id,
            title=rec.title,
            type=rec.type,
            status=rec.status,
            updated_at=rec.updated_at or rec.applied_at or rec.decided_at or rec.generated_at,
        )
        for rec in recommendations
        if rec.status in {
            RecommendationStatus.applied,
            RecommendationStatus.approved,
            RecommendationStatus.rejected,
            RecommendationStatus.expired,
        }
    ][:5]

    analysis_status = "ready"
    if recommendations:
        latest = max(recommendations, key=lambda rec: rec.generated_at)
        analysis_status = latest.analysis_status
        last_generated_at = latest.generated_at
    else:
        last_generated_at = None

    return ManagerSummaryRead(
        store_id=store_id,
        analysis_status=analysis_status,
        last_generated_at=last_generated_at,
        low_stock_count=sum(1 for item in insights if item.low_stock),
        anomaly_count=sum(1 for item in insights if item.anomaly_flag),
        pending_price_recommendations=sum(1 for rec in pending if rec.type == RecommendationType.price_change),
        pending_reorder_recommendations=sum(1 for rec in pending if rec.type == RecommendationType.reorder),
        pending_stock_anomalies=sum(1 for rec in pending if rec.type == RecommendationType.stock_anomaly),
        open_purchase_orders=supply_summary.open_purchase_orders,
        active_work_orders=supply_summary.active_work_orders,
        in_transit_transfers=supply_summary.in_transit_transfers,
        purchased_units=supply_summary.purchased_units,
        material_units=supply_summary.material_units,
        finished_units=supply_summary.finished_units,
        recent_outcomes=recent_outcomes,
    )


async def trigger_analysis(
    store_id: UUID,
    actor_user_id: UUID,
    payload: RecommendationTriggerRequest,
) -> RecommendationTriggerResponse:
    now = datetime.now(timezone.utc)
    bucket = _bucket_start(now).isoformat()
    existing_recent = list_recommendations(store_id)
    reusable: dict[str, RecommendationRead] = {}
    for rec in existing_recent:
        if not rec.dedupe_key:
            continue
        if rec.generated_at < now - timedelta(hours=6):
            continue
        if rec.status not in {
            RecommendationStatus.pending,
            RecommendationStatus.approved,
            RecommendationStatus.queued,
            RecommendationStatus.unavailable,
        }:
            continue
        reusable.setdefault(rec.dedupe_key, rec)

    insights = list_inventory_insights(store_id, lookback_days=payload.lookback_days)

    multica_response = await analyze_inventory_health(
        str(store_id),
        low_stock_threshold=payload.low_stock_threshold,
    )
    multica_payload = multica_response.payload or {}
    multica_status = str(multica_payload.get("status") or multica_response.model_used or "offline")
    analysis_status = "completed" if multica_status not in {"offline", "error", "fallback"} else "unavailable"

    critical_skus: set[str] = set()
    for raw in multica_payload.get("critical_skus", []):
        if isinstance(raw, dict):
            for key in ("sku_id", "sku_code"):
                value = raw.get(key)
                if value:
                    critical_skus.add(str(value))
        elif raw:
            critical_skus.add(str(raw))

    latest_prices = _latest_price_by_sku(store_id)
    created: list[RecommendationRead] = []
    reused: list[RecommendationRead] = []
    source = (
        AuditSource.multica_recommendation
        if analysis_status == "completed"
        else AuditSource.system
    )

    for insight in insights:
        proposals: list[dict[str, Any]] = []

        if insight.low_stock or (insight.days_of_cover is not None and insight.days_of_cover <= 7):
            suggested_qty = max(
                insight.reorder_qty,
                insight.reorder_level + max(0, insight.reorder_level - insight.qty_on_hand),
            )
            if insight.sourcing_strategy == SourcingStrategy.supplier_premade and insight.purchased_qty > 0:
                reorder_title = f"Deliver purchased stock for {insight.sku_code}"
                reorder_rationale = (
                    f"{insight.description} has {insight.purchased_qty} purchased units upstream while finished store "
                    f"stock is only {insight.qty_on_hand}. Move available supplier stock into finished inventory first."
                )
                reorder_impact = "Convert upstream purchased stock into finished store stock without waiting on a new PO."
                workflow_action = "transfer"
            elif insight.inventory_type == InventoryType.material:
                reorder_title = f"Replenish material {insight.sku_code}"
                reorder_rationale = (
                    f"{insight.description} is a material input with {insight.material_qty} units on hand and "
                    f"{insight.material_incoming_qty} inbound. That risks blocking manufacturing for standard and custom production."
                )
                reorder_impact = "Protect upcoming manufacturing runs by replenishing raw materials."
                workflow_action = "purchase_order"
            elif insight.sourcing_strategy in {
                SourcingStrategy.manufactured_standard,
                SourcingStrategy.manufactured_custom,
            }:
                production_label = (
                    "custom build"
                    if insight.sourcing_strategy == SourcingStrategy.manufactured_custom
                    else "production run"
                )
                reorder_title = f"Schedule {production_label} for {insight.sku_code}"
                reorder_rationale = (
                    f"{insight.description} is a manufactured finished good with {insight.finished_qty} finished units, "
                    f"{insight.material_qty} material units, and {insight.active_work_order_count} active work orders. "
                    f"Recent demand suggests it is time to stage the next {production_label}."
                )
                reorder_impact = "Reduce stockout risk by pushing manufacturing before stores run dry."
                workflow_action = "work_order"
            else:
                supplier_context = f" from {insight.supplier_name}" if insight.supplier_name else ""
                reorder_title = f"Reorder supplier stock for {insight.sku_code}"
                reorder_rationale = (
                    f"{insight.description} is at {insight.qty_on_hand} units versus a reorder level of "
                    f"{insight.reorder_level}. Recent 30-day sales are {insight.recent_sales_qty} units. "
                    f"Purchased upstream stock is {insight.purchased_qty} units and inbound supplier stock is "
                    f"{insight.purchased_incoming_qty} units{supplier_context}."
                )
                reorder_impact = "Reduce stockout risk for the pilot store."
                workflow_action = "purchase_order"
            proposals.append(
                {
                    "type": RecommendationType.reorder,
                    "title": reorder_title,
                    "rationale": reorder_rationale,
                    "confidence": 0.84 if insight.recent_sales_qty > 0 else 0.62,
                    "suggested_order_qty": max(suggested_qty, 1),
                    "workflow_action": workflow_action,
                    "expected_impact": reorder_impact,
                    "supporting_metrics": {
                        "qty_on_hand": insight.qty_on_hand,
                        "reorder_level": insight.reorder_level,
                        "reorder_qty": insight.reorder_qty,
                        "recent_sales_qty": insight.recent_sales_qty,
                        "recent_sales_revenue": insight.recent_sales_revenue,
                        "days_of_cover": insight.days_of_cover,
                        "inventory_type": insight.inventory_type.value,
                        "sourcing_strategy": insight.sourcing_strategy.value,
                        "supplier_name": insight.supplier_name,
                        "purchased_qty": insight.purchased_qty,
                        "purchased_incoming_qty": insight.purchased_incoming_qty,
                        "material_qty": insight.material_qty,
                        "material_incoming_qty": insight.material_incoming_qty,
                        "material_allocated_qty": insight.material_allocated_qty,
                        "finished_qty": insight.finished_qty,
                        "in_transit_qty": insight.in_transit_qty,
                        "active_work_order_count": insight.active_work_order_count,
                        "workflow_action": workflow_action,
                    },
                }
            )

        if insight.anomaly_flag or str(insight.sku_id) in critical_skus or insight.sku_code in critical_skus:
            proposals.append(
                {
                    "type": RecommendationType.stock_anomaly,
                    "title": f"Investigate stock anomaly for {insight.sku_code}",
                    "rationale": insight.anomaly_reason
                    or f"Multica flagged {insight.sku_code} for follow-up based on inventory health signals.",
                    "confidence": 0.71,
                    "expected_impact": "Prevent hidden shrinkage or overstock from distorting replenishment decisions.",
                    "supporting_metrics": {
                        "qty_on_hand": insight.qty_on_hand,
                        "recent_sales_qty": insight.recent_sales_qty,
                        "days_of_cover": insight.days_of_cover,
                        "inventory_type": insight.inventory_type.value,
                        "sourcing_strategy": insight.sourcing_strategy.value,
                        "purchased_qty": insight.purchased_qty,
                        "material_qty": insight.material_qty,
                        "finished_qty": insight.finished_qty,
                        "in_transit_qty": insight.in_transit_qty,
                        "active_work_order_count": insight.active_work_order_count,
                    },
                }
            )

        price_doc = latest_prices.get(str(insight.sku_id))
        cost_price = insight.cost_price or 0
        current_price = insight.current_price or 0
        margin_ratio = ((current_price - cost_price) / current_price) if current_price and cost_price else None

        if current_price and price_doc and (insight.finished_qty > 0 or insight.qty_on_hand > 0):
            if insight.qty_on_hand > max(insight.reorder_level * 4, insight.reorder_qty * 3, 12) and insight.recent_sales_qty <= max(1, insight.reorder_qty):
                suggested_price = round(current_price * 0.95, 2)
                proposals.append(
                    {
                        "type": RecommendationType.price_change,
                        "title": f"Review markdown for {insight.sku_code}",
                        "rationale": (
                            f"{insight.description} is carrying {insight.qty_on_hand} units with limited recent movement. "
                            "A small markdown can improve sell-through without auto-applying a change."
                        ),
                        "confidence": 0.67,
                        "current_price": current_price,
                        "suggested_price": suggested_price,
                        "workflow_action": "price_review",
                        "expected_impact": "Improve sell-through on slow-moving stock.",
                        "supporting_metrics": {
                            "qty_on_hand": insight.qty_on_hand,
                            "recent_sales_qty": insight.recent_sales_qty,
                            "recent_sales_revenue": insight.recent_sales_revenue,
                            "current_price_excl_tax": price_doc.get("price_excl_tax"),
                            "price_unit": price_doc.get("price_unit", 1),
                            "valid_to": price_doc.get("valid_to"),
                            "margin_ratio": round(margin_ratio, 4) if margin_ratio is not None else None,
                            "inventory_type": insight.inventory_type.value,
                            "sourcing_strategy": insight.sourcing_strategy.value,
                            "finished_qty": insight.finished_qty,
                            "workflow_action": "price_review",
                        },
                    }
                )
            elif insight.low_stock and insight.recent_sales_qty >= max(3, insight.reorder_qty) and (margin_ratio or 0) >= 0.2:
                suggested_price = round(current_price * 1.04, 2)
                proposals.append(
                    {
                        "type": RecommendationType.price_change,
                        "title": f"Review premium price for {insight.sku_code}",
                        "rationale": (
                            f"{insight.description} is moving quickly while inventory is constrained. "
                            "A modest price increase may protect margin without requiring an immediate price push."
                        ),
                        "confidence": 0.61,
                        "current_price": current_price,
                        "suggested_price": suggested_price,
                        "workflow_action": "price_review",
                        "expected_impact": "Protect margin during a low-stock period.",
                        "supporting_metrics": {
                            "qty_on_hand": insight.qty_on_hand,
                            "recent_sales_qty": insight.recent_sales_qty,
                            "recent_sales_revenue": insight.recent_sales_revenue,
                            "current_price_excl_tax": price_doc.get("price_excl_tax"),
                            "price_unit": price_doc.get("price_unit", 1),
                            "valid_to": price_doc.get("valid_to"),
                            "margin_ratio": round(margin_ratio, 4) if margin_ratio is not None else None,
                            "inventory_type": insight.inventory_type.value,
                            "sourcing_strategy": insight.sourcing_strategy.value,
                            "finished_qty": insight.finished_qty,
                            "workflow_action": "price_review",
                        },
                    }
                )

        for proposal in proposals:
            dedupe_key = f"{proposal['type'].value}:{proposal.get('workflow_action')}:{insight.sku_id}:{bucket}"
            if not payload.force_refresh and dedupe_key in reusable:
                reused.append(reusable[dedupe_key])
                continue

            recommendation_id = str(uuid_mod.uuid4())
            doc = {
                "id": recommendation_id,
                "store_id": str(store_id),
                "sku_id": str(insight.sku_id),
                "inventory_id": str(insight.inventory_id) if insight.inventory_id else None,
                "inventory_type": insight.inventory_type.value,
                "sourcing_strategy": insight.sourcing_strategy.value,
                "supplier_name": insight.supplier_name,
                "type": proposal["type"].value,
                "status": RecommendationStatus.pending.value,
                "title": proposal["title"],
                "rationale": proposal["rationale"],
                "confidence": proposal["confidence"],
                "supporting_metrics": proposal.get("supporting_metrics", {}),
                "source": source.value,
                "expected_impact": proposal.get("expected_impact"),
                "current_price": proposal.get("current_price"),
                "suggested_price": proposal.get("suggested_price"),
                "suggested_order_qty": proposal.get("suggested_order_qty"),
                "workflow_action": proposal.get("workflow_action"),
                "analysis_status": analysis_status,
                "generated_at": now,
                "dedupe_key": dedupe_key,
                "created_at": now,
                "updated_at": now,
                "created_by": str(actor_user_id),
                "updated_by": str(actor_user_id),
            }
            created_doc = create_document(
                recommendation_collection(store_id),
                doc,
                doc_id=recommendation_id,
            )
            created.append(_recommendation_from_doc(created_doc))

    created.sort(key=lambda item: item.generated_at, reverse=True)
    await _maybe_notify_opensclaw(
        "inventory_analysis",
        {
            "store_id": str(store_id),
            "analysis_status": analysis_status,
            "created_count": len(created),
            "low_stock_count": sum(1 for item in insights if item.low_stock),
            "anomaly_count": sum(1 for item in insights if item.anomaly_flag),
        },
    )

    return RecommendationTriggerResponse(
        analysis_status=analysis_status,
        multica_status=multica_status,
        recommendations_created=len(created),
        recommendations_reused=len(reused),
        recommendations=[_recommendation_public_view(item) for item in created + reused],
    )


def _find_recommendation_doc(store_id: UUID, recommendation_id: UUID) -> dict[str, Any]:
    doc = get_document(recommendation_collection(store_id), str(recommendation_id))
    if doc is None:
        raise ValueError("Recommendation not found")
    return doc


def approve_recommendation(
    store_id: UUID,
    recommendation_id: UUID,
    actor_user_id: UUID,
    payload: RecommendationDecisionRequest,
) -> RecommendationRead:
    return _update_recommendation_status(
        store_id,
        recommendation_id,
        actor_user_id,
        payload,
        target_status=RecommendationStatus.approved,
    )


def reject_recommendation(
    store_id: UUID,
    recommendation_id: UUID,
    actor_user_id: UUID,
    payload: RecommendationDecisionRequest,
) -> RecommendationRead:
    return _update_recommendation_status(
        store_id,
        recommendation_id,
        actor_user_id,
        payload,
        target_status=RecommendationStatus.rejected,
    )


def _update_recommendation_status(
    store_id: UUID,
    recommendation_id: UUID,
    actor_user_id: UUID,
    payload: RecommendationDecisionRequest,
    *,
    target_status: RecommendationStatus,
) -> RecommendationRead:
    doc = _find_recommendation_doc(store_id, recommendation_id)
    now = datetime.now(timezone.utc)
    updates = {
        "status": target_status.value,
        "decided_at": now,
        "decided_by": str(actor_user_id),
        "note": payload.note,
        "updated_at": now,
        "updated_by": str(actor_user_id),
    }
    updated = update_document(recommendation_collection(store_id), str(recommendation_id), updates)
    return _recommendation_from_doc(updated)


def apply_recommendation(
    store_id: UUID,
    recommendation_id: UUID,
    actor_user_id: UUID,
    payload: RecommendationApplyRequest,
) -> RecommendationRead:
    recommendation = _recommendation_from_doc(_find_recommendation_doc(store_id, recommendation_id))
    if recommendation.status != RecommendationStatus.approved:
        raise ValueError("Only approved recommendations can be applied")

    now = datetime.now(timezone.utc)
    if recommendation.type == RecommendationType.reorder and recommendation.sku_id is not None:
        workflow_action = recommendation.workflow_action or str(
            recommendation.supporting_metrics.get("workflow_action") or "purchase_order"
        )
        recommended_qty = max(recommendation.suggested_order_qty or 1, 1)
        if workflow_action == "transfer":
            transfer = create_stock_transfer(
                store_id,
                StockTransferCreate(
                    sku_id=recommendation.sku_id,
                    quantity=recommended_qty,
                    from_inventory_type=InventoryType.purchased,
                    to_inventory_type=InventoryType.finished,
                    note=payload.note or recommendation.title,
                    recommendation_id=recommendation.id,
                    source=SupplyActionSource.recommendation,
                ),
                actor_user_id,
            )
            receive_stock_transfer(
                store_id,
                transfer.id,
                StockTransferReceiveRequest(note=payload.note or "Applied from inventory recommendation."),
                actor_user_id,
            )
        elif workflow_action == "work_order":
            matching_bom = next(
                (item for item in list_bom_recipes(store_id) if item.finished_sku_id == recommendation.sku_id),
                None,
            )
            work_order_type = (
                WorkOrderType.custom
                if recommendation.sourcing_strategy == SourcingStrategy.manufactured_custom
                else WorkOrderType.standard
            )
            create_work_order(
                store_id,
                WorkOrderCreate(
                    finished_sku_id=recommendation.sku_id,
                    target_quantity=recommended_qty,
                    bom_id=matching_bom.id if matching_bom else None,
                    work_order_type=work_order_type if matching_bom else WorkOrderType.custom,
                    custom_components=[],
                    due_date=payload.effective_date,
                    note=payload.note or recommendation.title,
                    recommendation_id=recommendation.id,
                    source=SupplyActionSource.recommendation,
                ),
                actor_user_id,
            )
        else:
            suppliers = list_suppliers(store_id, active_only=True)
            supplier = next(
                (item for item in suppliers if recommendation.supplier_name and item.name == recommendation.supplier_name),
                None,
            ) or (suppliers[0] if suppliers else None)
            if supplier is None and recommendation.supplier_name:
                supplier = create_supplier(
                    store_id,
                    SupplierCreate(name=recommendation.supplier_name),
                    actor_user_id,
                )
            if supplier is None:
                raise ValueError("A supplier is required before applying a reorder recommendation")
            unit_cost = float(recommendation.supporting_metrics.get("unit_cost") or 0)
            if unit_cost <= 0:
                unit_cost = recommendation.current_price or 0
            create_purchase_order(
                store_id,
                PurchaseOrderCreate(
                    supplier_id=supplier.id,
                    lines=[
                        PurchaseOrderLineCreate(
                            sku_id=recommendation.sku_id,
                            quantity=recommended_qty,
                            unit_cost=max(unit_cost, 0),
                            note=payload.note or recommendation.title,
                        )
                    ],
                    ordered_at=payload.effective_date,
                    note=payload.note or recommendation.rationale,
                    recommendation_id=recommendation.id,
                    source=SupplyActionSource.recommendation,
                ),
                actor_user_id,
            )

    if recommendation.type == RecommendationType.price_change and recommendation.suggested_price is not None and recommendation.sku_id is not None:
        metrics = recommendation.supporting_metrics
        current_price = recommendation.current_price or 0
        current_ex_tax = metrics.get("current_price_excl_tax")
        if current_price and current_ex_tax is not None:
            ratio = float(current_ex_tax) / float(current_price)
            suggested_ex_tax = round(float(recommendation.suggested_price) * ratio, 2)
        else:
            suggested_ex_tax = recommendation.suggested_price

        price_id = str(uuid_mod.uuid4())
        valid_to = metrics.get("valid_to") or date(2099, 12, 31).isoformat()
        effective_date = payload.effective_date.isoformat() if payload.effective_date else date.today().isoformat()
        create_document(
            price_collection(store_id),
            {
                "id": price_id,
                "sku_id": str(recommendation.sku_id),
                "store_id": str(store_id),
                "price_incl_tax": recommendation.suggested_price,
                "price_excl_tax": suggested_ex_tax,
                "price_unit": int(metrics.get("price_unit", 1) or 1),
                "valid_from": effective_date,
                "valid_to": valid_to,
                "source": AuditSource.multica_recommendation.value,
                "recommendation_id": str(recommendation.id),
                "created_by": str(actor_user_id),
                "updated_by": str(actor_user_id),
                "created_at": now,
                "updated_at": now,
            },
            doc_id=price_id,
        )

    updated = update_document(
        recommendation_collection(store_id),
        str(recommendation_id),
        {
            "status": RecommendationStatus.applied.value,
            "applied_at": now,
            "applied_by": str(actor_user_id),
            "note": payload.note,
            "updated_at": now,
            "updated_by": str(actor_user_id),
        },
    )
    return _recommendation_from_doc(updated)


async def _maybe_notify_opensclaw(event_type: str, payload: dict[str, Any]) -> None:
    if not settings.OPENCLAW_WEBHOOK_URL:
        return
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            await client.post(
                settings.OPENCLAW_WEBHOOK_URL,
                json={"event_type": event_type, "payload": payload},
            )
    except Exception as exc:  # pragma: no cover - best-effort notification
        logger.warning("OpenClaw notification failed: %s", exc)
