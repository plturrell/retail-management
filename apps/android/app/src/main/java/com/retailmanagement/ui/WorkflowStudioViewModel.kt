package com.retailmanagement.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.retailmanagement.data.api.RetrofitClient
import com.retailmanagement.data.model.*
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class WorkflowStudioViewModel : ViewModel() {

    private val api get() = RetrofitClient.api

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading.asStateFlow()
    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()
    private val _actionKey = MutableStateFlow<String?>(null)
    val actionKey: StateFlow<String?> = _actionKey.asStateFlow()
    private val _successMessage = MutableStateFlow<String?>(null)
    val successMessage: StateFlow<String?> = _successMessage.asStateFlow()

    private val _suppliers = MutableStateFlow<List<SupplierSummary>>(emptyList())
    val suppliers: StateFlow<List<SupplierSummary>> = _suppliers.asStateFlow()
    private val _purchaseOrders = MutableStateFlow<List<PurchaseOrderSummary>>(emptyList())
    val purchaseOrders: StateFlow<List<PurchaseOrderSummary>> = _purchaseOrders.asStateFlow()
    private val _bomRecipes = MutableStateFlow<List<BOMRecipeSummary>>(emptyList())
    val bomRecipes: StateFlow<List<BOMRecipeSummary>> = _bomRecipes.asStateFlow()
    private val _workOrders = MutableStateFlow<List<WorkOrderSummary>>(emptyList())
    val workOrders: StateFlow<List<WorkOrderSummary>> = _workOrders.asStateFlow()
    private val _transfers = MutableStateFlow<List<StockTransferSummary>>(emptyList())
    val transfers: StateFlow<List<StockTransferSummary>> = _transfers.asStateFlow()
    private val _insights = MutableStateFlow<List<InventoryInsight>>(emptyList())
    val insights: StateFlow<List<InventoryInsight>> = _insights.asStateFlow()

    fun loadAll(storeId: String) {
        viewModelScope.launch {
            _isLoading.value = true
            _error.value = null
            try {
                val suppliersD = async { api.listSuppliers(storeId) }
                val posD       = async { api.listPurchaseOrders(storeId) }
                val bomD       = async { api.listBomRecipes(storeId) }
                val woD        = async { api.listWorkOrders(storeId) }
                val txD        = async { api.listTransfers(storeId) }
                val invD       = async { api.getInventoryInsights(storeId) }

                _suppliers.value     = suppliersD.await().data
                _purchaseOrders.value = posD.await().data
                _bomRecipes.value    = bomD.await().data
                _workOrders.value    = woD.await().data
                _transfers.value     = txD.await().data
                _insights.value      = invD.await().data
            } catch (e: Exception) {
                _error.value = e.message ?: "Failed to load supply chain data"
            }
            _isLoading.value = false
        }
    }

    fun saveSupplier(
        storeId: String,
        existingId: String?,
        name: String,
        contactName: String,
        email: String,
        phone: String,
        leadTimeDays: Int,
        currency: String,
        notes: String,
        isActive: Boolean,
        onSuccess: () -> Unit
    ) {
        if (name.isBlank()) { _error.value = "Supplier name is required."; return }
        _actionKey.value = "supplier-save"
        viewModelScope.launch {
            try {
                val body = SupplierBody(
                    name = name.trim(),
                    contactName = contactName.trim().ifBlank { null },
                    email = email.trim().ifBlank { null },
                    phone = phone.trim().ifBlank { null },
                    leadTimeDays = leadTimeDays,
                    currency = currency.trim().uppercase().ifBlank { "SGD" },
                    notes = notes.trim().ifBlank { null },
                    isActive = isActive
                )
                if (existingId != null) api.updateSupplier(storeId, existingId, body)
                else api.createSupplier(storeId, body)
                _successMessage.value = if (existingId != null) "Supplier updated." else "Supplier created."
                loadAll(storeId)
                onSuccess()
            } catch (e: Exception) { _error.value = e.message }
            _actionKey.value = null
        }
    }

    fun createPurchaseOrder(
        storeId: String,
        supplierId: String,
        skuId: String,
        quantity: Int,
        unitCost: Double,
        expectedDate: String?,
        note: String,
        onSuccess: () -> Unit
    ) {
        if (supplierId.isBlank() || skuId.isBlank()) { _error.value = "Supplier and SKU are required."; return }
        _actionKey.value = "po-create"
        viewModelScope.launch {
            try {
                api.createPurchaseOrder(storeId, PurchaseOrderCreateBody(
                    supplierId = supplierId,
                    lines = listOf(PurchaseOrderLineBody(skuId, maxOf(quantity, 1), maxOf(unitCost, 0.0), note.ifBlank { null })),
                    expectedDeliveryDate = expectedDate?.ifBlank { null },
                    note = note.ifBlank { null }
                ))
                _successMessage.value = "Purchase order created."
                loadAll(storeId)
                onSuccess()
            } catch (e: Exception) { _error.value = e.message }
            _actionKey.value = null
        }
    }

    fun receivePurchaseOrder(storeId: String, poId: String, onSuccess: () -> Unit) {
        _actionKey.value = "po-receive-$poId"
        viewModelScope.launch {
            try {
                api.receivePurchaseOrder(storeId, poId, mapOf("note" to "Received from Android manager console."))
                _successMessage.value = "Purchase order received."
                loadAll(storeId)
                onSuccess()
            } catch (e: Exception) { _error.value = e.message }
            _actionKey.value = null
        }
    }

    fun createBomRecipe(
        storeId: String,
        finishedSkuId: String,
        name: String,
        yieldQty: Int,
        components: List<BOMComponent>,
        notes: String,
        onSuccess: () -> Unit
    ) {
        val filtered = components.filter { it.skuId.isNotBlank() && it.quantityRequired > 0 }
        if (name.isBlank() || filtered.isEmpty()) { _error.value = "Recipe name and at least one component required."; return }
        _actionKey.value = "bom-create"
        viewModelScope.launch {
            try {
                api.createBomRecipe(storeId, BOMRecipeCreateBody(
                    finishedSkuId = finishedSkuId,
                    name = name.trim(),
                    yieldQuantity = maxOf(yieldQty, 1),
                    components = filtered,
                    notes = notes.ifBlank { null }
                ))
                _successMessage.value = "BOM recipe created."
                loadAll(storeId)
                onSuccess()
            } catch (e: Exception) { _error.value = e.message }
            _actionKey.value = null
        }
    }

    fun createWorkOrder(
        storeId: String,
        finishedSkuId: String,
        targetQty: Int,
        bomId: String?,
        workOrderType: String,
        customComponents: List<BOMComponent>,
        dueDate: String?,
        note: String,
        onSuccess: () -> Unit
    ) {
        val filtered = customComponents.filter { it.skuId.isNotBlank() && it.quantityRequired > 0 }
        if (bomId.isNullOrBlank() && filtered.isEmpty()) { _error.value = "Select a BOM or add custom components."; return }
        _actionKey.value = "wo-create"
        viewModelScope.launch {
            try {
                api.createWorkOrder(storeId, WorkOrderCreateBody(
                    finishedSkuId = finishedSkuId,
                    targetQuantity = maxOf(targetQty, 1),
                    bomId = bomId?.ifBlank { null },
                    workOrderType = workOrderType,
                    customComponents = if (bomId.isNullOrBlank()) filtered else emptyList(),
                    dueDate = dueDate?.ifBlank { null },
                    note = note.ifBlank { null }
                ))
                _successMessage.value = "Work order created."
                loadAll(storeId)
                onSuccess()
            } catch (e: Exception) { _error.value = e.message }
            _actionKey.value = null
        }
    }

    fun startWorkOrder(storeId: String, woId: String) {
        _actionKey.value = "wo-start-$woId"
        viewModelScope.launch {
            try {
                api.startWorkOrder(storeId, woId, emptyMap())
                loadAll(storeId)
            } catch (e: Exception) { _error.value = e.message }
            _actionKey.value = null
        }
    }

    fun completeWorkOrder(storeId: String, woId: String) {
        _actionKey.value = "wo-complete-$woId"
        viewModelScope.launch {
            try {
                api.completeWorkOrder(storeId, woId, mapOf("note" to "Completed from Android manager console."))
                loadAll(storeId)
            } catch (e: Exception) { _error.value = e.message }
            _actionKey.value = null
        }
    }

    fun createTransfer(
        storeId: String,
        skuId: String,
        quantity: Int,
        fromType: String,
        toType: String,
        note: String,
        onSuccess: () -> Unit
    ) {
        _actionKey.value = "tx-create"
        viewModelScope.launch {
            try {
                api.createTransfer(storeId, StockTransferCreateBody(
                    skuId = skuId,
                    quantity = maxOf(quantity, 1),
                    fromInventoryType = fromType,
                    toInventoryType = toType,
                    note = note.ifBlank { null }
                ))
                _successMessage.value = "Transfer created."
                loadAll(storeId)
                onSuccess()
            } catch (e: Exception) { _error.value = e.message }
            _actionKey.value = null
        }
    }

    fun clearMessages() { _error.value = null; _successMessage.value = null }
}
