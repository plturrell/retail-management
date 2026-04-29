package com.retailmanagement.ui.owner

import android.app.Application
import android.content.Context
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.google.gson.Gson
import com.retailmanagement.data.api.RetrofitClient
import com.retailmanagement.data.owner.*
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

    /**
     * Fetch a single supplier order from the live FastAPI endpoint.
     * Defaults to the Hengwei Craft 364-365 invoice currently under review.
     */
    fun loadOrder(supplierId: String = "CN-001", orderNumber: String = "364-365") {
        viewModelScope.launch {
            _isLoading.value = true
            _error.value = null
            try {
                val record = RetrofitClient.api.getSupplierReviewOrder(supplierId, orderNumber)
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
                _error.value = "Failed to load supplier order $orderNumber: ${e.message}"
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
