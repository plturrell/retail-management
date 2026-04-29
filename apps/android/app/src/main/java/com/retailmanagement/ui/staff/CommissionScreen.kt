package com.retailmanagement.ui.staff

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.retailmanagement.data.api.RetrofitClient
import com.retailmanagement.data.model.CommissionRuleRead
import com.retailmanagement.data.model.CommissionTierRead
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Mobile parity for the staff-portal CommissionPage. Aggregates the current
 * user's payslips into the latest 6 months of sales + commission and lists
 * the active tier rules for the store. Skips the Recharts bar chart used on
 * web — the Compose chart is replaced with a horizontal Surface bar so we
 * stay dependency-free.
 */
data class CommissionMonth(
    val key: String,    // "yyyy-MM"
    val label: String,  // "Apr"
    val sales: Double,
    val commission: Double
)

class CommissionViewModel : ViewModel() {
    private val _months = MutableStateFlow<List<CommissionMonth>>(emptyList())
    val months = _months.asStateFlow()
    private val _rules = MutableStateFlow<List<CommissionRuleRead>>(emptyList())
    val rules = _rules.asStateFlow()
    private val _isLoading = MutableStateFlow(false)
    val isLoading = _isLoading.asStateFlow()
    private val _error = MutableStateFlow<String?>(null)
    val error = _error.asStateFlow()

    fun load(storeId: String, userId: String) {
        if (storeId.isBlank() || userId.isBlank()) return
        viewModelScope.launch {
            _isLoading.value = true
            _error.value = null
            try {
                _rules.value = RetrofitClient.api.listCommissionRules(storeId).data
                val runs = RetrofitClient.api.listPayrollRuns(storeId).data
                val bucket = mutableMapOf<String, Triple<String, Double, Double>>()
                for (run in runs.filter { it.status == "approved" || it.status == "calculated" }) {
                    val detail = RetrofitClient.api.getPayrollRun(storeId, run.id).data
                    val mine = detail.payslips.filter { it.userId == userId }
                    if (mine.isEmpty()) continue
                    val key = run.periodStart.take(7)
                    val label = monthLabel(run.periodStart)
                    val sums = mine.fold(0.0 to 0.0) { acc, s ->
                        (acc.first + s.commissionSales) to (acc.second + s.commissionAmount)
                    }
                    val prev = bucket[key] ?: Triple(label, 0.0, 0.0)
                    bucket[key] = Triple(label, prev.second + sums.first, prev.third + sums.second)
                }
                _months.value = bucket.entries
                    .sortedBy { it.key }
                    .takeLast(6)
                    .map { (k, v) -> CommissionMonth(k, v.first, v.second, v.third) }
            } catch (e: Exception) {
                _error.value = e.localizedMessage ?: "Could not load commission."
            } finally {
                _isLoading.value = false
            }
        }
    }

    private fun monthLabel(periodStart: String): String {
        // periodStart "yyyy-MM-dd"; return localised short month, e.g. "Apr".
        val month = periodStart.substring(5, 7).toIntOrNull() ?: return periodStart.take(7)
        val labels = listOf("Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec")
        return labels.getOrElse(month - 1) { periodStart.take(7) }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CommissionScreen(storeId: String, userId: String, vm: CommissionViewModel = viewModel()) {
    val months by vm.months.collectAsState()
    val rules by vm.rules.collectAsState()
    val isLoading by vm.isLoading.collectAsState()
    val error by vm.error.collectAsState()
    LaunchedEffect(storeId, userId) { vm.load(storeId, userId) }

    val totalSales = months.sumOf { it.sales }
    val totalCommission = months.sumOf { it.commission }

    Scaffold(topBar = { TopAppBar(title = { Text("Commission") }) }) { padding ->
        when {
            isLoading -> Box(Modifier.fillMaxSize().padding(padding), Alignment.Center) {
                CircularProgressIndicator()
            }
            error != null -> Box(Modifier.fillMaxSize().padding(padding), Alignment.Center) {
                Text(error!!, color = MaterialTheme.colorScheme.error)
            }
            months.isEmpty() && rules.isEmpty() -> Box(Modifier.fillMaxSize().padding(padding), Alignment.Center) {
                Text("No commission yet", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            else -> LazyColumn(
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
                modifier = Modifier.fillMaxSize().padding(padding)
            ) {
                item { SummaryCard(totalSales, totalCommission) }
                if (months.isNotEmpty()) item { Text("Monthly", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold) }
                items(months) { MonthBar(it, totalCommission.coerceAtLeast(1.0)) }
                if (rules.isNotEmpty()) item { Text("Tier rules", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold) }
                items(rules) { RuleCard(it) }
            }
        }
    }
}

@Composable
private fun SummaryCard(sales: Double, commission: Double) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(12.dp), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Metric("6-mo sales", "$" + "%,.0f".format(sales))
            Metric("6-mo commission", "$" + "%,.0f".format(commission), Color(0xFF1E8A44))
        }
    }
}

@Composable
private fun Metric(label: String, value: String, tint: Color = Color.Unspecified) {
    Column { Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant); Text(value, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = tint) }
}

@Composable
private fun MonthBar(m: CommissionMonth, denom: Double) {
    val pct = (m.commission / denom).toFloat().coerceIn(0f, 1f)
    Column(Modifier.fillMaxWidth()) {
        Row { Text(m.label, modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodySmall); Text("$" + "%,.0f".format(m.commission), style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.SemiBold) }
        Box(Modifier.fillMaxWidth().height(8.dp).clip(RoundedCornerShape(4.dp)).background(MaterialTheme.colorScheme.surfaceVariant)) {
            Box(Modifier.fillMaxWidth(pct).height(8.dp).background(Color(0xFF1E8A44)))
        }
    }
}

@Composable
private fun RuleCard(rule: CommissionRuleRead) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(rule.name, fontWeight = FontWeight.SemiBold)
            rule.tiers.forEach { Text(tierLine(it), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
    }
}

private fun tierLine(tier: CommissionTierRead): String {
    val rng = if (tier.max != null) "$" + "%,.0f".format(tier.min) + " – $" + "%,.0f".format(tier.max) else "$" + "%,.0f".format(tier.min) + "+"
    return "$rng     ${"%.1f".format(tier.rate * 100)}%"
}
