package com.retailmanagement.data.owner

import com.google.gson.annotations.SerializedName

data class VendorReviewOrderRecord(
    @SerializedName("order_number") val orderNumber: String,
    @SerializedName("order_date") val orderDate: String,
    @SerializedName("supplier_id") val supplierId: String,
    @SerializedName("supplier_name") val supplierName: String,
    val currency: String,
    @SerializedName("source_document_total_amount") val sourceDocumentTotalAmount: Double,
    @SerializedName("document_payment_status") val documentPaymentStatus: String,
    @SerializedName("item_reconciliation_status") val itemReconciliationStatus: String?,
    @SerializedName("line_items") val lineItems: List<VendorReviewLineItem>
)

data class VendorReviewLineItem(
    @SerializedName("source_line_number") val sourceLineNumber: Int,
    @SerializedName("supplier_item_code") val supplierItemCode: String?,
    @SerializedName("unit_cost_cny") val unitCostCny: Double?,
    val quantity: Int?,
    @SerializedName("line_total_cny") val lineTotalCny: Double?,
    val size: String?,
    @SerializedName("material_description") val materialDescription: String?,
    @SerializedName("display_name") val displayName: String?
)

enum class ReviewLineStatus {
    @SerializedName("unreviewed") UNREVIEWED,
    @SerializedName("verified") VERIFIED,
    @SerializedName("needs_follow_up") NEEDS_FOLLOW_UP
}

data class ReviewLineState(
    var status: ReviewLineStatus,
    var note: String,
    var targetSkuId: String,
    var updatedAt: Long?
)

data class ReviewOrderState(
    var lines: MutableMap<String, ReviewLineState>
)

data class SupplierReviewWorkspaceState(
    var schemaVersion: Int,
    var supplierId: String,
    var savedAt: Long?,
    var orders: MutableMap<String, ReviewOrderState>
)
