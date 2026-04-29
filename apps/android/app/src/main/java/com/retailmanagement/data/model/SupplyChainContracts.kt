package com.retailmanagement.data.model

import com.google.gson.annotations.SerializedName

// ── Supplier ────────────────────────────────────────────────────────────────

data class SupplierSummary(
    val id: String,
    val name: String,
    @SerializedName("contact_name") val contactName: String? = null,
    val email: String? = null,
    val phone: String? = null,
    @SerializedName("lead_time_days") val leadTimeDays: Int = 7,
    val currency: String = "SGD",
    val notes: String? = null,
    @SerializedName("is_active") val isActive: Boolean = true
)

data class SupplierBody(
    val name: String,
    @SerializedName("contact_name") val contactName: String? = null,
    val email: String? = null,
    val phone: String? = null,
    @SerializedName("lead_time_days") val leadTimeDays: Int = 7,
    val currency: String = "SGD",
    val notes: String? = null,
    @SerializedName("is_active") val isActive: Boolean = true
)

// ── Purchase Orders ──────────────────────────────────────────────────────────

data class PurchaseOrderLine(
    val id: String? = null,
    @SerializedName("line_id") val lineId: String? = null,
    @SerializedName("sku_id") val skuId: String,
    val quantity: Int,
    @SerializedName("unit_cost") val unitCost: Double,
    @SerializedName("open_quantity") val openQuantity: Int = 0,
    val note: String? = null
)

data class PurchaseOrderSummary(
    val id: String,
    @SerializedName("supplier_id") val supplierId: String,
    @SerializedName("supplier_name") val supplierName: String? = null,
    val status: String,
    val lines: List<PurchaseOrderLine> = emptyList(),
    @SerializedName("expected_delivery_date") val expectedDeliveryDate: String? = null,
    val note: String? = null,
    @SerializedName("created_at") val createdAt: String? = null
)

data class PurchaseOrderLineBody(
    @SerializedName("sku_id") val skuId: String,
    val quantity: Int,
    @SerializedName("unit_cost") val unitCost: Double,
    val note: String? = null
)

data class PurchaseOrderCreateBody(
    @SerializedName("supplier_id") val supplierId: String,
    val lines: List<PurchaseOrderLineBody>,
    @SerializedName("expected_delivery_date") val expectedDeliveryDate: String? = null,
    val note: String? = null,
    val source: String = "manual"
)

// ── BOM Recipes ──────────────────────────────────────────────────────────────

data class BOMComponent(
    @SerializedName("sku_id") val skuId: String,
    @SerializedName("quantity_required") val quantityRequired: Int,
    val note: String? = null
)

data class BOMRecipeSummary(
    val id: String,
    val name: String,
    @SerializedName("finished_sku_id") val finishedSkuId: String,
    @SerializedName("yield_quantity") val yieldQuantity: Int = 1,
    val components: List<BOMComponent> = emptyList(),
    val notes: String? = null
)

data class BOMRecipeCreateBody(
    @SerializedName("finished_sku_id") val finishedSkuId: String,
    val name: String,
    @SerializedName("yield_quantity") val yieldQuantity: Int,
    val components: List<BOMComponent>,
    val notes: String? = null
)

// ── Work Orders ───────────────────────────────────────────────────────────────

data class WorkOrderSummary(
    val id: String,
    @SerializedName("finished_sku_id") val finishedSkuId: String,
    @SerializedName("target_quantity") val targetQuantity: Int,
    @SerializedName("completed_quantity") val completedQuantity: Int = 0,
    @SerializedName("bom_id") val bomId: String? = null,
    @SerializedName("work_order_type") val workOrderType: String = "standard",
    val status: String,
    @SerializedName("due_date") val dueDate: String? = null,
    val note: String? = null
)

data class WorkOrderCreateBody(
    @SerializedName("finished_sku_id") val finishedSkuId: String,
    @SerializedName("target_quantity") val targetQuantity: Int,
    @SerializedName("bom_id") val bomId: String? = null,
    @SerializedName("work_order_type") val workOrderType: String,
    @SerializedName("custom_components") val customComponents: List<BOMComponent> = emptyList(),
    @SerializedName("due_date") val dueDate: String? = null,
    val note: String? = null,
    val source: String = "manual"
)

// ── Stock Transfers ───────────────────────────────────────────────────────────

data class StockTransferSummary(
    val id: String,
    @SerializedName("sku_id") val skuId: String,
    val quantity: Int,
    @SerializedName("from_inventory_type") val fromInventoryType: String,
    @SerializedName("to_inventory_type") val toInventoryType: String,
    val status: String,
    val note: String? = null
)

data class StockTransferCreateBody(
    @SerializedName("sku_id") val skuId: String,
    val quantity: Int,
    @SerializedName("from_inventory_type") val fromInventoryType: String,
    @SerializedName("to_inventory_type") val toInventoryType: String,
    val note: String? = null,
    val source: String = "manual"
)

// ── Inventory Insight (supply chain fields) ───────────────────────────────────

data class SupplyChainSummary(
    @SerializedName("total_purchase_orders") val totalPurchaseOrders: Int = 0,
    @SerializedName("open_work_orders") val openWorkOrders: Int = 0,
    @SerializedName("pending_transfers") val pendingTransfers: Int = 0,
    @SerializedName("active_suppliers") val activeSuppliers: Int = 0
)
