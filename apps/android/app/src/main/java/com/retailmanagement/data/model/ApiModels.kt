package com.retailmanagement.data.model

import com.google.gson.annotations.SerializedName
import java.math.BigDecimal

// ── Generic API wrappers ──

data class DataResponse<T>(
    val success: Boolean = true,
    val message: String = "OK",
    val data: T
)

data class PaginatedResponse<T>(
    val success: Boolean = true,
    val message: String = "OK",
    val data: List<T>,
    val total: Int,
    val page: Int,
    @SerializedName("page_size") val pageSize: Int
)

// ── Schedule / Shift ──

data class ShiftRead(
    val id: String,
    @SerializedName("schedule_id") val scheduleId: String,
    @SerializedName("user_id") val userId: String,
    @SerializedName("shift_date") val shiftDate: String,
    @SerializedName("start_time") val startTime: String,
    @SerializedName("end_time") val endTime: String,
    @SerializedName("break_minutes") val breakMinutes: Int = 60,
    val notes: String? = null,
    val hours: Double = 0.0,
    @SerializedName("created_at") val createdAt: String? = null
)

// ── Timesheet ──

data class ClockInRequest(
    @SerializedName("store_id") val storeId: String,
    val notes: String? = null
)

data class ClockOutRequest(
    @SerializedName("break_minutes") val breakMinutes: Int = 0,
    val notes: String? = null
)

data class TimeEntryRead(
    val id: String,
    @SerializedName("user_id") val userId: String,
    @SerializedName("store_id") val storeId: String,
    @SerializedName("clock_in") val clockIn: String,
    @SerializedName("clock_out") val clockOut: String? = null,
    @SerializedName("break_minutes") val breakMinutes: Int = 0,
    val notes: String? = null,
    val status: String,
    @SerializedName("approved_by") val approvedBy: String? = null,
    @SerializedName("hours_worked") val hoursWorked: Double? = null,
    @SerializedName("created_at") val createdAt: String? = null
)

// ── Payroll / Payslip ──

data class PaySlipRead(
    val id: String,
    @SerializedName("payroll_run_id") val payrollRunId: String,
    @SerializedName("user_id") val userId: String,
    @SerializedName("basic_salary") val basicSalary: Double,
    @SerializedName("hours_worked") val hoursWorked: Double? = null,
    @SerializedName("overtime_hours") val overtimeHours: Double = 0.0,
    @SerializedName("overtime_pay") val overtimePay: Double = 0.0,
    val allowances: Double = 0.0,
    val deductions: Double = 0.0,
    @SerializedName("commission_sales") val commissionSales: Double = 0.0,
    @SerializedName("commission_amount") val commissionAmount: Double = 0.0,
    @SerializedName("gross_pay") val grossPay: Double,
    @SerializedName("cpf_employee") val cpfEmployee: Double,
    @SerializedName("cpf_employer") val cpfEmployer: Double,
    @SerializedName("net_pay") val netPay: Double,
    val notes: String? = null,
    @SerializedName("created_at") val createdAt: String? = null
)

data class PayrollRunSummary(
    val id: String,
    @SerializedName("store_id") val storeId: String,
    @SerializedName("period_start") val periodStart: String,
    @SerializedName("period_end") val periodEnd: String,
    val status: String,
    @SerializedName("total_gross") val totalGross: Double,
    @SerializedName("total_net") val totalNet: Double,
    @SerializedName("created_at") val createdAt: String? = null
)

data class PayrollRunRead(
    val id: String,
    @SerializedName("store_id") val storeId: String,
    @SerializedName("period_start") val periodStart: String,
    @SerializedName("period_end") val periodEnd: String,
    val status: String,
    @SerializedName("total_gross") val totalGross: Double,
    @SerializedName("total_cpf_employee") val totalCpfEmployee: Double,
    @SerializedName("total_cpf_employer") val totalCpfEmployer: Double,
    @SerializedName("total_net") val totalNet: Double,
    val payslips: List<PaySlipRead> = emptyList()
)

// ── Staff Performance ──

data class StaffPerformanceItem(
    @SerializedName("user_id") val userId: String,
    @SerializedName("full_name") val fullName: String,
    @SerializedName("total_sales") val totalSales: Double,
    @SerializedName("order_count") val orderCount: Int,
    @SerializedName("avg_order_value") val avgOrderValue: Double,
    val rank: Int
)

data class StaffPerformanceOverview(
    @SerializedName("generated_at") val generatedAt: String,
    @SerializedName("store_id") val storeId: String,
    @SerializedName("period_from") val periodFrom: String,
    @SerializedName("period_to") val periodTo: String,
    val staff: List<StaffPerformanceItem>,
    @SerializedName("total_store_sales") val totalStoreSales: Double
)

data class StaffInsightsResponse(
    @SerializedName("user_id") val userId: String,
    @SerializedName("full_name") val fullName: String,
    val summary: Map<String, Any>? = null,
    @SerializedName("ai_insights") val aiInsights: String? = null
)

// ── User / Profile ──

data class UserRead(
    val id: String,
    val email: String,
    @SerializedName("full_name") val fullName: String,
    val phone: String? = null,
    @SerializedName("firebase_uid") val firebaseUid: String,
    @SerializedName("store_roles") val storeRoles: List<UserStoreRoleRead>? = null
)

data class UserStoreRoleRead(
    val id: String,
    @SerializedName("user_id") val userId: String? = null,
    @SerializedName("store_id") val storeId: String,
    val role: String
)

data class EmployeeProfileRead(
    val id: String,
    @SerializedName("user_id") val userId: String,
    @SerializedName("date_of_birth") val dateOfBirth: String,
    val nationality: String,
    @SerializedName("basic_salary") val basicSalary: Double,
    @SerializedName("hourly_rate") val hourlyRate: Double? = null,
    @SerializedName("commission_rate") val commissionRate: Double? = null,
    @SerializedName("bank_name") val bankName: String,
    @SerializedName("start_date") val startDate: String,
    @SerializedName("end_date") val endDate: String? = null,
    @SerializedName("is_active") val isActive: Boolean
)

// ── Manager inventory / iOS InventoryTabView parity ──

data class ManagerSummary(
    @SerializedName("low_stock_count") val lowStockCount: Int = 0,
    @SerializedName("anomaly_count") val anomalyCount: Int = 0,
    @SerializedName("pending_reorder_recommendations") val pendingReorderRecommendations: Int = 0,
    @SerializedName("pending_price_recommendations") val pendingPriceRecommendations: Int = 0,
    @SerializedName("pending_stock_anomalies") val pendingStockAnomalies: Int = 0,
    @SerializedName("finished_units") val finishedUnits: Double = 0.0,
    @SerializedName("last_generated_at") val lastGeneratedAt: String? = null,
    @SerializedName("analysis_status") val analysisStatus: String? = null
)

data class InventoryInsight(
    @SerializedName("sku_id") val skuId: String,
    @SerializedName("inventory_id") val inventoryId: String? = null,
    @SerializedName("sku_code") val skuCode: String,
    val description: String,
    @SerializedName("long_description") val longDescription: String? = null,
    @SerializedName("inventory_type") val inventoryType: String = "finished",
    @SerializedName("sourcing_strategy") val sourcingStrategy: String = "supplier_premade",
    @SerializedName("current_price") val currentPrice: Double? = null,
    @SerializedName("cost_price") val costPrice: Double? = null,
    @SerializedName("qty_on_hand") val qtyOnHand: Double = 0.0,
    @SerializedName("finished_qty") val finishedQty: Double = 0.0,
    @SerializedName("finished_allocated_qty") val finishedAllocatedQty: Double = 0.0,
    @SerializedName("reorder_level") val reorderLevel: Double = 0.0,
    @SerializedName("reorder_qty") val reorderQty: Double = 0.0,
    @SerializedName("recent_sales_qty") val recentSalesQty: Double = 0.0,
    @SerializedName("days_of_cover") val daysOfCover: Double? = null,
    @SerializedName("low_stock") val lowStock: Boolean = false,
    @SerializedName("anomaly_flag") val anomalyFlag: Boolean = false,
    @SerializedName("anomaly_reason") val anomalyReason: String? = null,
    @SerializedName("pending_recommendation_count") val pendingRecommendationCount: Int = 0
)

data class ManagerRecommendation(
    val id: String,
    @SerializedName("store_id") val storeId: String? = null,
    @SerializedName("sku_id") val skuId: String? = null,
    @SerializedName("sku_code") val skuCode: String? = null,
    val type: String,
    val status: String,
    val title: String,
    val rationale: String,
    val confidence: Double = 0.0,
    @SerializedName("inventory_type") val inventoryType: String? = null,
    @SerializedName("sourcing_strategy") val sourcingStrategy: String? = null,
    @SerializedName("supplier_name") val supplierName: String? = null,
    @SerializedName("current_price") val currentPrice: Double? = null,
    @SerializedName("suggested_price") val suggestedPrice: Double? = null,
    @SerializedName("suggested_order_qty") val suggestedOrderQty: Double? = null,
    @SerializedName("expected_impact") val expectedImpact: String? = null,
    @SerializedName("workflow_action") val workflowAction: String? = null,
    @SerializedName("generated_at") val generatedAt: String? = null
)

data class RecommendationDecisionBody(
    val note: String? = null
)

// ── Master Data / iOS MasterDataView parity ──

data class MasterDataStats(
    val total: Int = 0,
    @SerializedName("sale_ready") val saleReady: Int = 0,
    @SerializedName("needs_price_flag") val needsPriceFlag: Int = 0,
    @SerializedName("needs_review_flag") val needsReviewFlag: Int = 0,
    @SerializedName("sale_ready_missing_price") val saleReadyMissingPrice: Int = 0,
    @SerializedName("by_supplier") val bySupplier: Map<String, Int> = emptyMap()
)

data class MasterDataProductRow(
    @SerializedName("sku_code") val skuCode: String,
    @SerializedName("internal_code") val internalCode: String? = null,
    @SerializedName("supplier_id") val supplierId: String? = null,
    @SerializedName("supplier_name") val supplierName: String? = null,
    val description: String? = null,
    val material: String? = null,
    @SerializedName("product_type") val productType: String? = null,
    val size: String? = null,
    @SerializedName("qty_on_hand") val qtyOnHand: Double? = null,
    @SerializedName("cost_price") val costPrice: Double? = null,
    @SerializedName("retail_price") val retailPrice: Double? = null,
    @SerializedName("retail_price_note") val retailPriceNote: String? = null,
    @SerializedName("sale_ready") val saleReady: Boolean = false,
    @SerializedName("needs_retail_price") val needsRetailPrice: Boolean = false,
    @SerializedName("nec_plu") val necPlu: String? = null
)

data class MasterDataProductsResponse(
    val count: Int,
    val products: List<MasterDataProductRow>
)

data class MasterDataProductPatch(
    @SerializedName("retail_price") val retailPrice: Double? = null,
    @SerializedName("sale_ready") val saleReady: Boolean? = null,
    @SerializedName("block_sales") val blockSales: Boolean? = null,
    val notes: String? = null
)

data class MasterDataExportResult(
    val ok: Boolean,
    @SerializedName("exit_code") val exitCode: Int,
    @SerializedName("output_path") val outputPath: String? = null,
    @SerializedName("download_url") val downloadUrl: String? = null,
    val stdout: String = "",
    val stderr: String = ""
)

data class IngestPreviewItem(
    @SerializedName("line_number") val lineNumber: Int? = null,
    @SerializedName("supplier_item_code") val supplierItemCode: String? = null,
    @SerializedName("product_name_en") val productNameEn: String? = null,
    val material: String? = null,
    @SerializedName("product_type") val productType: String? = null,
    val size: String? = null,
    val quantity: Int? = null,
    @SerializedName("unit_price_cny") val unitPriceCny: Double? = null,
    @SerializedName("proposed_sku") val proposedSku: String? = null,
    @SerializedName("proposed_plu") val proposedPlu: String? = null,
    @SerializedName("proposed_cost_sgd") val proposedCostSgd: Double? = null,
    @SerializedName("already_exists") val alreadyExists: Boolean = false,
    @SerializedName("existing_sku") val existingSku: String? = null,
    @SerializedName("skip_reason") val skipReason: String? = null
)

data class IngestPreviewSummary(
    @SerializedName("total_lines") val totalLines: Int = 0,
    @SerializedName("new_skus") val newSkus: Int = 0,
    @SerializedName("already_exists") val alreadyExists: Int = 0,
    val skipped: Int = 0
)

data class IngestPreview(
    @SerializedName("upload_id") val uploadId: String,
    @SerializedName("document_type") val documentType: String? = null,
    @SerializedName("document_number") val documentNumber: String? = null,
    @SerializedName("document_date") val documentDate: String? = null,
    @SerializedName("supplier_name") val supplierName: String? = null,
    val currency: String? = null,
    @SerializedName("document_total") val documentTotal: Double? = null,
    val items: List<IngestPreviewItem> = emptyList(),
    val summary: IngestPreviewSummary = IngestPreviewSummary()
)

data class IngestCommitRequest(
    @SerializedName("upload_id") val uploadId: String,
    val items: List<IngestPreviewItem>,
    @SerializedName("supplier_id") val supplierId: String = "CN-001",
    @SerializedName("supplier_name") val supplierName: String = "Hengwei Craft",
    @SerializedName("order_number") val orderNumber: String? = null
)

data class IngestCommitResult(
    val added: Int = 0,
    val skipped: Int = 0,
    @SerializedName("added_entries") val addedEntries: List<MasterDataProductRow> = emptyList()
)

data class PriceRecommendation(
    @SerializedName("sku_code") val skuCode: String,
    @SerializedName("recommended_retail_sgd") val recommendedRetailSgd: Double,
    @SerializedName("implied_margin_pct") val impliedMarginPct: Int? = null,
    val confidence: String = "low",
    @SerializedName("comparable_skus") val comparableSkus: List<String>? = null,
    val rationale: String = ""
)

data class PriceRecommendationsResponse(
    @SerializedName("rules_inferred") val rulesInferred: List<String>? = null,
    val recommendations: List<PriceRecommendation> = emptyList(),
    val notes: String? = null,
    @SerializedName("n_priced_examples") val pricedExamplesCount: Int? = null,
    @SerializedName("n_targets") val targetCount: Int? = null
)

data class RecommendPricesRequest(
    @SerializedName("target_skus") val targetSkus: List<String>? = null,
    @SerializedName("max_targets") val maxTargets: Int = 80
)
