package com.retailmanagement.data.owner

import com.google.gson.annotations.SerializedName

// MARK: - Enums
// Gson handles strings directly if we use enums, but for safety we can just use Strings or String-based enums.
enum class RecommendationType(val value: String) {
    @SerializedName("reorder") REORDER("reorder"),
    @SerializedName("price_change") PRICE_CHANGE("price_change"),
    @SerializedName("stock_anomaly") STOCK_ANOMALY("stock_anomaly")
}

enum class RecommendationStatus(val value: String) {
    @SerializedName("pending") PENDING("pending"),
    @SerializedName("approved") APPROVED("approved"),
    @SerializedName("dismissed") DISMISSED("dismissed")
}

// MARK: - Manager Summary

data class RecommendationOutcome(
    @SerializedName("recommendation_id") val recommendationId: String,
    @SerializedName("sku_id") val skuId: String,
    val title: String,
    val type: String,
    val status: String,
    @SerializedName("updated_at") val updatedAt: String
)

data class ManagerSummary(
    @SerializedName("store_id") val storeId: String,
    @SerializedName("analysis_status") val analysisStatus: String,
    @SerializedName("last_generated_at") val lastGeneratedAt: String,
    @SerializedName("low_stock_count") val lowStockCount: Int,
    @SerializedName("anomaly_count") val anomalyCount: Int,
    @SerializedName("pending_price_recommendations") val pendingPriceRecommendations: Int,
    @SerializedName("pending_reorder_recommendations") val pendingReorderRecommendations: Int,
    @SerializedName("pending_stock_anomalies") val pendingStockAnomalies: Int,
    @SerializedName("open_purchase_orders") val openPurchaseOrders: Int,
    @SerializedName("active_work_orders") val activeWorkOrders: Int,
    @SerializedName("in_transit_transfers") val inTransitTransfers: Int,
    @SerializedName("purchased_units") val purchasedUnits: Int,
    @SerializedName("material_units") val materialUnits: Int,
    @SerializedName("finished_units") val finishedUnits: Int,
    @SerializedName("recent_outcomes") val recentOutcomes: List<RecommendationOutcome> = emptyList()
)

data class ManagerRecommendation(
    val id: String,
    @SerializedName("store_id") val storeId: String,
    @SerializedName("sku_id") val skuId: String,
    @SerializedName("inventory_id") val inventoryId: String? = null,
    val type: String,
    val status: String,
    val title: String,
    val rationale: String,
    val confidence: Double,
    val source: String,
    @SerializedName("expected_impact") val expectedImpact: String,
    @SerializedName("current_price") val currentPrice: Double? = null,
    @SerializedName("suggested_price") val suggestedPrice: Double? = null,
    @SerializedName("suggested_order_qty") val suggestedOrderQty: Int? = null,
    @SerializedName("workflow_action") val workflowAction: String,
    @SerializedName("analysis_status") val analysisStatus: String,
    @SerializedName("generated_at") val generatedAt: String,
    @SerializedName("decided_at") val decidedAt: String? = null,
    @SerializedName("applied_at") val appliedAt: String? = null,
    val note: String? = null
)

data class ApprovalBody(
    val note: String
)
