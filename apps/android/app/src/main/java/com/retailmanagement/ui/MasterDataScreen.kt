package com.retailmanagement.ui

import android.app.Application
import android.net.Uri
import android.webkit.MimeTypeMap
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Print
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Save
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalContext
import android.content.Intent
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.retailmanagement.data.api.RetrofitClient
import com.retailmanagement.data.model.IngestCommitRequest
import com.retailmanagement.data.model.IngestPreview
import com.retailmanagement.data.model.IngestPreviewItem
import com.retailmanagement.data.model.MasterDataExportResult
import com.retailmanagement.data.model.MasterDataProductPatch
import com.retailmanagement.data.model.MasterDataProductRow
import com.retailmanagement.data.model.MasterDataStats
import com.retailmanagement.data.model.PriceRecommendation
import com.retailmanagement.data.model.PriceRecommendationsResponse
import com.retailmanagement.data.model.RecommendPricesRequest
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody

data class MasterDataDraft(
    val product: MasterDataProductRow,
    val price: String = product.retailPrice?.toString() ?: "",
    val notes: String = product.retailPriceNote ?: "",
    val saleReady: Boolean = product.saleReady,
    val status: String = ""
)

data class IngestPreviewUi(
    val preview: IngestPreview,
    val selectedCodes: Set<String>
)

data class PriceRecommendationsUi(
    val response: PriceRecommendationsResponse,
    val selectedSkus: Set<String>
)

class MasterDataViewModel(application: Application) : AndroidViewModel(application) {
    private val _stats = MutableStateFlow<MasterDataStats?>(null)
    val stats = _stats.asStateFlow()
    private val _rows = MutableStateFlow<List<MasterDataDraft>>(emptyList())
    val rows = _rows.asStateFlow()
    private val _isLoading = MutableStateFlow(false)
    val isLoading = _isLoading.asStateFlow()
    private val _busyLabel = MutableStateFlow<String?>(null)
    val busyLabel = _busyLabel.asStateFlow()
    private val _error = MutableStateFlow<String?>(null)
    val error = _error.asStateFlow()
    private val _lastExport = MutableStateFlow<MasterDataExportResult?>(null)
    val lastExport = _lastExport.asStateFlow()
    private val _ingestPreview = MutableStateFlow<IngestPreviewUi?>(null)
    val ingestPreview = _ingestPreview.asStateFlow()
    private val _priceRecommendations = MutableStateFlow<PriceRecommendationsUi?>(null)
    val priceRecommendations = _priceRecommendations.asStateFlow()

    fun load() {
        viewModelScope.launch {
            _isLoading.value = true
            _error.value = null
            try {
                _stats.value = RetrofitClient.api.getMasterDataStats()
                _rows.value = RetrofitClient.api.listMasterDataProducts().products.map { MasterDataDraft(it) }
            } catch (e: Exception) {
                _error.value = e.message ?: "Failed to load master data"
            } finally {
                _isLoading.value = false
            }
        }
    }

    fun updatePrice(sku: String, price: String) {
        _rows.value = _rows.value.map { if (it.product.skuCode == sku) it.copy(price = price, status = "") else it }
    }

    fun updateNotes(sku: String, notes: String) {
        _rows.value = _rows.value.map { if (it.product.skuCode == sku) it.copy(notes = notes, status = "") else it }
    }

    fun updateSaleReady(sku: String, saleReady: Boolean) {
        _rows.value = _rows.value.map { if (it.product.skuCode == sku) it.copy(saleReady = saleReady, status = "") else it }
    }

    fun save(sku: String) {
        val row = _rows.value.firstOrNull { it.product.skuCode == sku } ?: return
        val price = row.price.toDoubleOrNull()
        if (price == null || price <= 0.0) {
            _rows.value = _rows.value.map { if (it.product.skuCode == sku) it.copy(status = "Enter a positive price") else it }
            return
        }
        viewModelScope.launch {
            _rows.value = _rows.value.map { if (it.product.skuCode == sku) it.copy(status = "Saving...") else it }
            try {
                val updated = RetrofitClient.api.patchMasterDataProduct(
                    sku,
                    MasterDataProductPatch(retailPrice = price, saleReady = row.saleReady, notes = row.notes.ifBlank { null })
                )
                _rows.value = _rows.value.map {
                    if (it.product.skuCode == sku) MasterDataDraft(updated, status = "Saved") else it
                }
                _stats.value = RetrofitClient.api.getMasterDataStats()
            } catch (e: Exception) {
                _rows.value = _rows.value.map { if (it.product.skuCode == sku) it.copy(status = e.message ?: "Save failed") else it }
            }
        }
    }

    fun exportNec() {
        viewModelScope.launch {
            _busyLabel.value = "Regenerating Excel..."
            _lastExport.value = null
            _error.value = null
            try {
                _lastExport.value = RetrofitClient.api.exportNecJewel(emptyMap())
            } catch (e: Exception) {
                _error.value = e.message ?: "Export failed"
            } finally {
                _busyLabel.value = null
            }
        }
    }

    fun uploadInvoice(uri: Uri) {
        viewModelScope.launch {
            _busyLabel.value = "OCR invoice..."
            _error.value = null
            try {
                val resolver = getApplication<Application>().contentResolver
                val bytes = resolver.openInputStream(uri)?.use { it.readBytes() }
                    ?: throw IllegalArgumentException("Could not read selected invoice")
                val type = resolver.getType(uri) ?: mimeTypeFromUri(uri) ?: "application/octet-stream"
                val name = fileNameFromUri(uri)
                val body = bytes.toRequestBody(type.toMediaTypeOrNull())
                val part = MultipartBody.Part.createFormData("file", name, body)
                val preview = RetrofitClient.api.ingestInvoice(part)
                val selected = preview.items
                    .filter { it.proposedSku != null && !it.alreadyExists && it.skipReason == null }
                    .mapNotNull { it.supplierItemCode }
                    .toSet()
                _ingestPreview.value = IngestPreviewUi(preview, selected)
            } catch (e: Exception) {
                _error.value = e.message ?: "Invoice ingest failed"
            } finally {
                _busyLabel.value = null
            }
        }
    }

    fun togglePreviewItem(code: String) {
        val current = _ingestPreview.value ?: return
        val next = if (current.selectedCodes.contains(code)) {
            current.selectedCodes - code
        } else {
            current.selectedCodes + code
        }
        _ingestPreview.value = current.copy(selectedCodes = next)
    }

    fun cancelIngest() {
        _ingestPreview.value = null
    }

    fun commitIngest() {
        val current = _ingestPreview.value ?: return
        val items = current.preview.items.filter { item ->
            item.supplierItemCode?.let { current.selectedCodes.contains(it) } == true
        }
        if (items.isEmpty()) {
            _error.value = "Select at least one invoice line to add"
            return
        }
        viewModelScope.launch {
            _busyLabel.value = "Adding products..."
            _error.value = null
            try {
                val result = RetrofitClient.api.commitInvoice(
                    IngestCommitRequest(
                        uploadId = current.preview.uploadId,
                        items = items,
                        orderNumber = current.preview.documentNumber
                    )
                )
                _ingestPreview.value = null
                _error.value = "Added ${result.added}; skipped ${result.skipped}"
                load()
            } catch (e: Exception) {
                _error.value = e.message ?: "Commit failed"
            } finally {
                _busyLabel.value = null
            }
        }
    }

    fun generatePriceRecommendations() {
        viewModelScope.launch {
            _busyLabel.value = "Generating AI prices..."
            _error.value = null
            try {
                val response = RetrofitClient.api.recommendPrices(RecommendPricesRequest())
                _priceRecommendations.value = PriceRecommendationsUi(
                    response,
                    response.recommendations.map { it.skuCode }.toSet()
                )
            } catch (e: Exception) {
                _error.value = e.message ?: "AI price recommendation failed"
            } finally {
                _busyLabel.value = null
            }
        }
    }

    fun toggleRecommendation(sku: String) {
        val current = _priceRecommendations.value ?: return
        val next = if (current.selectedSkus.contains(sku)) {
            current.selectedSkus - sku
        } else {
            current.selectedSkus + sku
        }
        _priceRecommendations.value = current.copy(selectedSkus = next)
    }

    fun cancelRecommendations() {
        _priceRecommendations.value = null
    }

    fun applyRecommendations() {
        val current = _priceRecommendations.value ?: return
        val selected = current.response.recommendations.filter { current.selectedSkus.contains(it.skuCode) }
        if (selected.isEmpty()) {
            _error.value = "Select at least one price recommendation"
            return
        }
        viewModelScope.launch {
            _busyLabel.value = "Applying AI prices..."
            _error.value = null
            try {
                selected.forEach { recommendation ->
                    val row = _rows.value.firstOrNull { it.product.skuCode == recommendation.skuCode }
                    val note = recommendationNote(row?.notes.orEmpty(), recommendation)
                    RetrofitClient.api.patchMasterDataProduct(
                        recommendation.skuCode,
                        MasterDataProductPatch(
                            retailPrice = recommendation.recommendedRetailSgd,
                            saleReady = row?.saleReady,
                            notes = note
                        )
                    )
                }
                _priceRecommendations.value = null
                _error.value = "Applied ${selected.size} AI price recommendation${if (selected.size == 1) "" else "s"}"
                load()
            } catch (e: Exception) {
                _error.value = e.message ?: "Could not apply recommendations"
            } finally {
                _busyLabel.value = null
            }
        }
    }

    private fun recommendationNote(existing: String, recommendation: PriceRecommendation): String {
        val comps = recommendation.comparableSkus.orEmpty()
        val comparable = if (comps.isEmpty()) "" else " comps: ${comps.joinToString(", ")}"
        val aiNote = "AI ${recommendation.confidence}: ${recommendation.rationale}$comparable"
        return if (existing.isBlank()) aiNote else "$existing | $aiNote"
    }

    private fun fileNameFromUri(uri: Uri): String {
        val extension = MimeTypeMap.getSingleton().getExtensionFromMimeType(getApplication<Application>().contentResolver.getType(uri))
        return "invoice-${System.currentTimeMillis()}${extension?.let { ".$it" } ?: ""}"
    }

    private fun mimeTypeFromUri(uri: Uri): String? {
        val extension = MimeTypeMap.getFileExtensionFromUrl(uri.toString())
        return MimeTypeMap.getSingleton().getMimeTypeFromExtension(extension)
    }

    fun printPosLabels(context: android.content.Context) {
        val toPrint = _rows.value.filter { it.saleReady }
        if (toPrint.isEmpty()) {
            _error.value = "No sale-ready items found in the current view to print."
            return
        }

        val builder = Uri.parse("http://localhost:8000/api/pos-labelling/print").buildUpon()
        toPrint.forEach { row ->
            builder.appendQueryParameter("skus", row.product.skuCode)
            val priceStr = if (row.price.isNotBlank()) "S$${row.price}" else ""
            builder.appendQueryParameter("prices", priceStr)
            builder.appendQueryParameter("names", row.product.description ?: "")
        }

        val intent = Intent(Intent.ACTION_VIEW, builder.build())
        context.startActivity(intent)
    }
}

@Composable
fun MasterDataScreen(canEdit: Boolean = false, vm: MasterDataViewModel = viewModel()) {
    val context = LocalContext.current
    val stats by vm.stats.collectAsState()
    val rows by vm.rows.collectAsState()
    val isLoading by vm.isLoading.collectAsState()
    val busyLabel by vm.busyLabel.collectAsState()
    val error by vm.error.collectAsState()
    val lastExport by vm.lastExport.collectAsState()
    val ingestPreview by vm.ingestPreview.collectAsState()
    val priceRecommendations by vm.priceRecommendations.collectAsState()
    val invoicePicker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (canEdit && uri != null) vm.uploadInvoice(uri)
    }

    LaunchedEffect(Unit) { vm.load() }

    LazyColumn(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Master Data", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                    Text(
                        if (canEdit) "Pricing, invoice ingest, AI recommendations, and NEC export sync through the backend"
                        else "Review POS-ready catalogue, price gaps, and SKU readiness. Owner access is required for changes.",
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                OutlinedButton(onClick = { vm.load() }) {
                    Icon(Icons.Default.Refresh, null)
                    Text("Refresh")
                }
            }
        }
        if (isLoading && rows.isEmpty()) {
            item { Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() } }
        }
        busyLabel?.let { item { Text(it, color = MaterialTheme.colorScheme.primary) } }
        error?.let { item { Text(it, color = MaterialTheme.colorScheme.error) } }
        stats?.let {
            item {
                ElevatedCard(Modifier.fillMaxWidth()) {
                    Row(Modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                        Stat("Products", it.total.toString())
                        Stat("Sale Ready", it.saleReady.toString())
                        Stat("Need Price", it.saleReadyMissingPrice.toString())
                    }
                }
            }
        }
        if (canEdit) item {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { invoicePicker.launch("*/*") }, enabled = busyLabel == null, modifier = Modifier.fillMaxWidth()) {
                    Text("OCR invoice")
                }
                Button(onClick = { vm.generatePriceRecommendations() }, enabled = busyLabel == null, modifier = Modifier.fillMaxWidth()) {
                    Text("AI recommend prices")
                }
                Button(onClick = { vm.exportNec() }, enabled = busyLabel == null, modifier = Modifier.fillMaxWidth()) {
                    Text("Regenerate NEC Excel")
                }
                OutlinedButton(onClick = { vm.printPosLabels(context) }, enabled = busyLabel == null, modifier = Modifier.fillMaxWidth()) {
                    Icon(imageVector = Icons.Default.Print, contentDescription = null)
                    Spacer(Modifier.padding(4.dp))
                    Text("Print POS Labels")
                }
            }
        }
        lastExport?.let {
            item {
                Text(
                    if (it.ok) "Excel regenerated: ${it.downloadUrl ?: "ready"}" else "Export failed: ${it.stderr.ifBlank { it.stdout }}",
                    color = if (it.ok) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error
                )
            }
        }
        if (canEdit) ingestPreview?.let { preview ->
            item {
                IngestPreviewCard(
                    preview = preview,
                    onToggle = vm::togglePreviewItem,
                    onCommit = vm::commitIngest,
                    onCancel = vm::cancelIngest
                )
            }
        }
        if (canEdit) priceRecommendations?.let { preview ->
            item {
                PriceRecommendationsCard(
                    preview = preview,
                    onToggle = vm::toggleRecommendation,
                    onApply = vm::applyRecommendations,
                    onCancel = vm::cancelRecommendations
                )
            }
        }
        items(rows, key = { it.product.skuCode }) { row ->
            MasterDataRowCard(
                row,
                onPrice = { vm.updatePrice(row.product.skuCode, it) },
                onNotes = { vm.updateNotes(row.product.skuCode, it) },
                onSaleReady = { vm.updateSaleReady(row.product.skuCode, it) },
                onSave = { vm.save(row.product.skuCode) },
                canEdit = canEdit
            )
        }
        item { Spacer(Modifier.height(80.dp)) }
    }
}

@Composable
private fun IngestPreviewCard(
    preview: IngestPreviewUi,
    onToggle: (String) -> Unit,
    onCommit: () -> Unit,
    onCancel: () -> Unit
) {
    ElevatedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Invoice preview", fontWeight = FontWeight.Bold)
            Text(
                "${preview.preview.supplierName ?: "Supplier"} - ${preview.preview.documentNumber ?: "No document number"} - ${preview.preview.summary.newSkus} new SKUs",
                style = MaterialTheme.typography.bodySmall
            )
            preview.preview.items.take(8).forEach { item ->
                IngestLine(
                    item,
                    item.supplierItemCode?.let { preview.selectedCodes.contains(it) } == true,
                    onToggle
                )
            }
            if (preview.preview.items.size > 8) {
                Text("+${preview.preview.items.size - 8} more lines", style = MaterialTheme.typography.bodySmall)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onCommit) { Text("Add ${preview.selectedCodes.size}") }
                OutlinedButton(onClick = onCancel) { Text("Cancel") }
            }
        }
    }
}

@Composable
private fun Stat(label: String, value: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun IngestLine(item: IngestPreviewItem, selected: Boolean, onToggle: (String) -> Unit) {
    val code = item.supplierItemCode
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
        Checkbox(
            checked = selected,
            enabled = code != null && !item.alreadyExists && item.skipReason == null,
            onCheckedChange = { if (code != null) onToggle(code) }
        )
        Column(Modifier.weight(1f)) {
            Text(item.proposedSku ?: item.existingSku ?: code ?: "Manual line", fontWeight = FontWeight.SemiBold)
            Text(item.productNameEn ?: item.skipReason ?: "Ready to add", style = MaterialTheme.typography.bodySmall)
            Text("Qty ${item.quantity ?: 0} - cost S$${item.proposedCostSgd ?: 0.0}", style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun PriceRecommendationsCard(
    preview: PriceRecommendationsUi,
    onToggle: (String) -> Unit,
    onApply: () -> Unit,
    onCancel: () -> Unit
) {
    ElevatedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("AI price recommendations", fontWeight = FontWeight.Bold)
            Text(
                "${preview.response.recommendations.size} suggestions - trained on ${preview.response.pricedExamplesCount ?: 0} priced examples",
                style = MaterialTheme.typography.bodySmall
            )
            preview.response.recommendations.take(8).forEach { rec ->
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
                    Checkbox(checked = preview.selectedSkus.contains(rec.skuCode), onCheckedChange = { onToggle(rec.skuCode) })
                    Column(Modifier.weight(1f)) {
                        Text("${rec.skuCode} - S$${rec.recommendedRetailSgd}", fontWeight = FontWeight.SemiBold)
                        Text("${rec.confidence} confidence - ${rec.rationale}", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
            if (preview.response.recommendations.size > 8) {
                Text("+${preview.response.recommendations.size - 8} more suggestions", style = MaterialTheme.typography.bodySmall)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onApply) { Text("Apply ${preview.selectedSkus.size}") }
                OutlinedButton(onClick = onCancel) { Text("Cancel") }
            }
        }
    }
}

@Composable
private fun MasterDataRowCard(
    row: MasterDataDraft,
    onPrice: (String) -> Unit,
    onNotes: (String) -> Unit,
    onSaleReady: (Boolean) -> Unit,
    onSave: () -> Unit,
    canEdit: Boolean
) {
    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(row.product.skuCode, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
            Text(row.product.description ?: "Untitled product", fontWeight = FontWeight.SemiBold)
            Text("${row.product.productType ?: "Type"} - ${row.product.material ?: "Material"} - Cost $${row.product.costPrice ?: 0.0}", style = MaterialTheme.typography.bodySmall)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(checked = row.saleReady, enabled = canEdit, onCheckedChange = onSaleReady)
                Text("Sale ready")
            }
            OutlinedTextField(
                value = row.price,
                onValueChange = onPrice,
                label = { Text("Retail SGD") },
                enabled = canEdit,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal, imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { onSave() }),
                modifier = Modifier.fillMaxWidth()
            )
            OutlinedTextField(
                value = row.notes,
                onValueChange = onNotes,
                label = { Text("Notes") },
                enabled = canEdit,
                modifier = Modifier.fillMaxWidth()
            )
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Text(row.status, style = MaterialTheme.typography.bodySmall, color = if (row.status == "Saved") MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error)
                if (canEdit) {
                    Button(onClick = onSave) {
                        Icon(Icons.Default.Save, null)
                        Text("Save")
                    }
                }
            }
        }
    }
}
