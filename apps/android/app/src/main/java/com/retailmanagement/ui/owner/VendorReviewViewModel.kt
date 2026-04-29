package com.retailmanagement.ui.owner

import android.app.Application
import android.content.Context
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.google.gson.Gson
import com.retailmanagement.data.owner.*
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class VendorReviewViewModel(application: Application) : AndroidViewModel(application) {
    private val gson = Gson()
    private val prefs = application.getSharedPreferences("vendor_review_CN-001", Context.MODE_PRIVATE)

    private val _order = MutableStateFlow<VendorReviewOrderRecord?>(null)
    val order: StateFlow<VendorReviewOrderRecord?> = _order.asStateFlow()

    private val _workspace = MutableStateFlow<SupplierReviewWorkspaceState>(loadWorkspace())
    val workspace: StateFlow<SupplierReviewWorkspaceState> = _workspace.asStateFlow()

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()

    private fun loadWorkspace(): SupplierReviewWorkspaceState {
        val saved = prefs.getString("workspace_data", null)
        if (saved != null) {
            try {
                return gson.fromJson(saved, SupplierReviewWorkspaceState::class.java)
            } catch (e: Exception) {
                // fallback
            }
        }
        return SupplierReviewWorkspaceState(
            schemaVersion = 2,
            supplierId = "CN-001",
            savedAt = null,
            orders = mutableMapOf()
        )
    }

    private fun saveWorkspace(ws: SupplierReviewWorkspaceState) {
        ws.savedAt = System.currentTimeMillis()
        prefs.edit().putString("workspace_data", gson.toJson(ws)).apply()
        _workspace.value = ws.copy() // trigger recomposition
    }

    fun loadMockData() {
        viewModelScope.launch {
            _isLoading.value = true
            delay(500) // Simulate network

            val mockJSON = """
            {
              "order_number": "364-365",
              "order_date": "2026-03-26",
              "supplier_id": "CN-001",
              "supplier_name": "Hengwei Craft",
              "currency": "CNY",
              "source_document_total_amount": 11046,
              "document_payment_status": "cash_paid",
              "item_reconciliation_status": "needs_follow_up",
              "line_items": [
                { "source_line_number": 1, "supplier_item_code": "A339A", "unit_cost_cny": 120, "quantity": 5, "line_total_cny": 600, "size": "8*8*10", "material_description": "Copper, Natural mineral stone" },
                { "source_line_number": 2, "supplier_item_code": "A339B", "unit_cost_cny": 105, "quantity": 5, "line_total_cny": 525, "size": "11.5*11.5*6", "material_description": "Copper, Natural mineral stone" },
                { "source_line_number": 3, "supplier_item_code": "H1444A", "unit_cost_cny": 360, "quantity": 2, "line_total_cny": 720, "size": "18*18*14", "material_description": "Copper, Natural brown crystal marble" },
                { "source_line_number": 10, "supplier_item_code": null, "display_name": "Guardian artwork", "unit_cost_cny": 2000, "quantity": 1, "line_total_cny": 2000, "material_description": "Malachite Tin" }
              ]
            }
            """.trimIndent()

            try {
                val record = gson.fromJson(mockJSON, VendorReviewOrderRecord::class.java)
                _order.value = record

                val currentWs = _workspace.value
                if (!currentWs.orders.containsKey(record.orderNumber)) {
                    val linesMap = mutableMapOf<String, ReviewLineState>()
                    record.lineItems.forEach { line ->
                        linesMap[line.sourceLineNumber.toString()] = ReviewLineState(
                            status = ReviewLineStatus.UNREVIEWED,
                            note = "",
                            targetSkuId = line.supplierItemCode ?: "",
                            updatedAt = null
                        )
                    }
                    currentWs.orders[record.orderNumber] = ReviewOrderState(lines = linesMap)
                    saveWorkspace(currentWs)
                }
            } catch (e: Exception) {
                _error.value = e.message
            }
            _isLoading.value = false
        }
    }

    fun updateLineStatus(orderNumber: String, lineKey: String, status: ReviewLineStatus, note: String) {
        val currentWs = _workspace.value
        val orderState = currentWs.orders[orderNumber] ?: return
        val lineState = orderState.lines[lineKey] ?: return

        lineState.status = status
        lineState.note = note
        lineState.updatedAt = System.currentTimeMillis()
        saveWorkspace(currentWs)
    }
}
