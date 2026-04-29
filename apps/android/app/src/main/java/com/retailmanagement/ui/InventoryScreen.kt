package com.retailmanagement.ui

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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.retailmanagement.data.api.RetrofitClient
import com.retailmanagement.data.model.InventoryInsight
import com.retailmanagement.data.model.ManagerSummary
import com.retailmanagement.data.model.ManagerRecommendation
import com.retailmanagement.data.model.RecommendationDecisionBody
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class InventoryViewModel : ViewModel() {
    private val _summary = MutableStateFlow<ManagerSummary?>(null)
    val summary = _summary.asStateFlow()
    private val _items = MutableStateFlow<List<InventoryInsight>>(emptyList())
    val items = _items.asStateFlow()
    private val _recommendations = MutableStateFlow<List<ManagerRecommendation>>(emptyList())
    val recommendations = _recommendations.asStateFlow()
    private val _isLoading = MutableStateFlow(false)
    val isLoading = _isLoading.asStateFlow()
    private val _busyAction = MutableStateFlow<String?>(null)
    val busyAction = _busyAction.asStateFlow()
    private val _error = MutableStateFlow<String?>(null)
    val error = _error.asStateFlow()

    fun load(storeId: String) {
        if (storeId.isBlank()) return
        viewModelScope.launch {
            _isLoading.value = true
            _error.value = null
            try {
                _summary.value = RetrofitClient.api.getManagerSummary(storeId).data
                _items.value = RetrofitClient.api.getInventoryInsights(storeId).data
                _recommendations.value = RetrofitClient.api.getManagerRecommendations(storeId).data
            } catch (e: Exception) {
                _error.value = e.message ?: "Failed to load inventory"
            } finally {
                _isLoading.value = false
            }
        }
    }

    fun analyze(storeId: String) {
        if (storeId.isBlank()) return
        viewModelScope.launch {
            _isLoading.value = true
            _error.value = null
            try {
                RetrofitClient.api.analyzeInventory(
                    storeId,
                    mapOf("force_refresh" to true, "lookback_days" to 30, "low_stock_threshold" to 5)
                )
                load(storeId)
            } catch (e: Exception) {
                _error.value = e.message ?: "Failed to analyze inventory"
                _isLoading.value = false
            }
        }
    }

    fun recommendationAction(storeId: String, recommendationId: String, action: String) {
        if (storeId.isBlank()) return
        viewModelScope.launch {
            _busyAction.value = recommendationId + action
            _error.value = null
            try {
                RetrofitClient.api.updateRecommendation(
                    storeId,
                    recommendationId,
                    action,
                    RecommendationDecisionBody(note = "Updated from Android")
                )
                load(storeId)
            } catch (e: Exception) {
                _error.value = e.message ?: "Failed to $action recommendation"
            } finally {
                _busyAction.value = null
            }
        }
    }
}

@Composable
fun InventoryScreen(storeId: String = "", vm: InventoryViewModel = viewModel()) {
    val summary by vm.summary.collectAsState()
    val items by vm.items.collectAsState()
    val recommendations by vm.recommendations.collectAsState()
    val isLoading by vm.isLoading.collectAsState()
    val busyAction by vm.busyAction.collectAsState()
    val error by vm.error.collectAsState()

    LaunchedEffect(storeId) { vm.load(storeId) }

    if (isLoading && items.isEmpty()) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        return
    }

    LazyColumn(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Column {
                    Text("Inventory", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                    Text("Manager stock health and recommendations", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                OutlinedButton(onClick = { vm.load(storeId) }) {
                    Icon(Icons.Default.Refresh, null)
                    Text("Refresh")
                }
            }
        }
        if (error != null) {
            item { Text(error!!, color = MaterialTheme.colorScheme.error) }
        }
        summary?.let { s ->
            item {
                ElevatedCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.Inventory2, null, tint = MaterialTheme.colorScheme.primary)
                            Text("Operations Summary", Modifier.padding(start = 8.dp), fontWeight = FontWeight.Bold)
                        }
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Stat("Low Stock", s.lowStockCount.toString())
                            Stat("Anomalies", s.anomalyCount.toString())
                            Stat("Reorders", s.pendingReorderRecommendations.toString())
                        }
                        Button(onClick = { vm.analyze(storeId) }, enabled = !isLoading, modifier = Modifier.fillMaxWidth()) {
                            Text(if (isLoading) "Analyzing..." else "Analyze Inventory")
                        }
                    }
                }
            }
        }
        items(items) { item ->
            InventoryInsightCard(item)
        }
        if (recommendations.isNotEmpty()) {
            item {
                Text("Recommendations", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            }
            items(recommendations, key = { it.id }) { recommendation ->
                RecommendationCard(
                    recommendation = recommendation,
                    busyAction = busyAction,
                    onAction = { action -> vm.recommendationAction(storeId, recommendation.id, action) }
                )
            }
        }
        item { Spacer(Modifier.height(80.dp)) }
    }
}

@Composable
private fun InventoryInsightCard(item: InventoryInsight) {
    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column(Modifier.weight(1f)) {
                    Text(item.skuCode, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                    Text(item.description, fontWeight = FontWeight.SemiBold)
                }
                Column(horizontalAlignment = Alignment.End) {
                    Text("Qty ${item.qtyOnHand}", fontWeight = FontWeight.Bold)
                    item.currentPrice?.let { Text("$${String.format("%.2f", it)}", style = MaterialTheme.typography.bodySmall) }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                if (item.lowStock) AssistChip(onClick = {}, label = { Text("Low stock") })
                if (item.anomalyFlag) AssistChip(onClick = {}, label = { Text("Anomaly") })
                if (item.pendingRecommendationCount > 0) AssistChip(onClick = {}, label = { Text("${item.pendingRecommendationCount} actions") })
            }
            item.anomalyReason?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
            }
        }
    }
}

@Composable
private fun RecommendationCard(
    recommendation: ManagerRecommendation,
    busyAction: String?,
    onAction: (String) -> Unit
) {
    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column(Modifier.weight(1f)) {
                    Text(recommendation.type.replace("_", " "), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                    Text(recommendation.title, fontWeight = FontWeight.SemiBold)
                }
                Text(recommendation.status, style = MaterialTheme.typography.bodySmall)
            }
            Text(recommendation.rationale, style = MaterialTheme.typography.bodySmall)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("${(recommendation.confidence * 100).toInt()}% confidence", style = MaterialTheme.typography.bodySmall)
                recommendation.suggestedPrice?.let { Text("S$${String.format("%.2f", it)}", style = MaterialTheme.typography.bodySmall) }
                recommendation.suggestedOrderQty?.let { Text("${it.toInt()} units", style = MaterialTheme.typography.bodySmall) }
            }
            recommendation.expectedImpact?.let {
                Text(it, style = MaterialTheme.typography.bodySmall)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (recommendation.status == "pending") {
                    OutlinedButton(
                        onClick = { onAction("reject") },
                        enabled = busyAction != recommendation.id + "reject"
                    ) { Text("Reject") }
                    Button(
                        onClick = { onAction("approve") },
                        enabled = busyAction != recommendation.id + "approve"
                    ) { Text("Approve") }
                } else if (recommendation.status == "approved") {
                    Button(
                        onClick = { onAction("apply") },
                        enabled = busyAction != recommendation.id + "apply"
                    ) { Text("Apply") }
                }
            }
        }
    }
}

@Composable
private fun Stat(label: String, value: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
