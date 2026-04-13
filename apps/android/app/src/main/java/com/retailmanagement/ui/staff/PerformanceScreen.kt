package com.retailmanagement.ui.staff

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.EmojiEvents
import androidx.compose.material.icons.filled.Insights
import androidx.compose.material.icons.filled.TrendingUp
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.retailmanagement.data.api.RetrofitClient
import com.retailmanagement.data.model.StaffInsightsResponse
import com.retailmanagement.data.model.StaffPerformanceItem
import com.retailmanagement.data.model.StaffPerformanceOverview
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.format.DateTimeFormatter

class PerformanceViewModel : ViewModel() {
    private val _overview = MutableStateFlow<StaffPerformanceOverview?>(null)
    val overview = _overview.asStateFlow()
    private val _insights = MutableStateFlow<StaffInsightsResponse?>(null)
    val insights = _insights.asStateFlow()
    private val _isLoading = MutableStateFlow(false)
    val isLoading = _isLoading.asStateFlow()
    private val _error = MutableStateFlow<String?>(null)
    val error = _error.asStateFlow()

    fun load(storeId: String, userId: String) {
        viewModelScope.launch {
            _isLoading.value = true
            try {
                val now = LocalDate.now()
                val from = now.minusDays(30).format(DateTimeFormatter.ISO_LOCAL_DATE)
                val to = now.format(DateTimeFormatter.ISO_LOCAL_DATE)
                _overview.value = RetrofitClient.api.getStaffPerformance(storeId, from, to)
                try {
                    _insights.value = RetrofitClient.api.getStaffInsights(storeId, userId)
                } catch (_: Exception) { /* insights optional */ }
            } catch (e: Exception) { _error.value = e.message }
            finally { _isLoading.value = false }
        }
    }
}

@Composable
fun PerformanceScreen(storeId: String, userId: String, vm: PerformanceViewModel = viewModel()) {
    val overview by vm.overview.collectAsState()
    val insights by vm.insights.collectAsState()
    val isLoading by vm.isLoading.collectAsState()
    val error by vm.error.collectAsState()
    LaunchedEffect(storeId) { vm.load(storeId, userId) }

    if (isLoading) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        return
    }
    if (error != null) {
        Box(Modifier.fillMaxSize().padding(16.dp), contentAlignment = Alignment.Center) {
            Text(error!!, color = MaterialTheme.colorScheme.error)
        }
        return
    }

    val me = overview?.staff?.find { it.userId == userId }
    val allStaff = overview?.staff ?: emptyList()

    LazyColumn(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        // My Sales Summary Card
        item {
            ElevatedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.TrendingUp, null, tint = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(8.dp))
                        Text("My Sales (Last 30 Days)", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    }
                    Spacer(Modifier.height(12.dp))
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                        StatColumn("Total Sales", "$${String.format("%.0f", me?.totalSales ?: 0.0)}")
                        StatColumn("Orders", "${me?.orderCount ?: 0}")
                        StatColumn("Avg Order", "$${String.format("%.0f", me?.avgOrderValue ?: 0.0)}")
                    }
                }
            }
        }

        // Simple trend visualization
        if (allStaff.isNotEmpty()) {
            item {
                ElevatedCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp)) {
                        Text("Team Sales Comparison", fontWeight = FontWeight.Bold)
                        Spacer(Modifier.height(8.dp))
                        val maxSales = allStaff.maxOf { it.totalSales }.coerceAtLeast(1.0)
                        val primaryColor = MaterialTheme.colorScheme.primary
                        val surfaceColor = MaterialTheme.colorScheme.surfaceVariant
                        Canvas(Modifier.fillMaxWidth().height((allStaff.size * 32).dp)) {
                            allStaff.forEachIndexed { i, s ->
                                val y = i * 32.dp.toPx() + 16.dp.toPx()
                                val barW = (s.totalSales / maxSales * size.width * 0.7).toFloat()
                                drawLine(surfaceColor, Offset(0f, y), Offset(size.width.toFloat(), y), 20f, StrokeCap.Round)
                                val color = if (s.userId == userId) primaryColor else Color.Gray
                                drawLine(color, Offset(0f, y), Offset(barW, y), 20f, StrokeCap.Round)
                            }
                        }
                        Spacer(Modifier.height(4.dp))
                        allStaff.forEach { s ->
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                Text(s.fullName, style = MaterialTheme.typography.bodySmall,
                                    fontWeight = if (s.userId == userId) FontWeight.Bold else FontWeight.Normal)
                                Text("$${String.format("%.0f", s.totalSales)}", style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
            }
        }

        // Peer Ranking
        item {
            ElevatedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.EmojiEvents, null, tint = MaterialTheme.colorScheme.tertiary)
                        Spacer(Modifier.width(8.dp))
                        Text("Ranking", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    }
                    Spacer(Modifier.height(8.dp))
                    allStaff.forEach { s ->
                        Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("#${s.rank} ${s.fullName}",
                                fontWeight = if (s.userId == userId) FontWeight.Bold else FontWeight.Normal)
                            Text("$${String.format("%.0f", s.totalSales)}")
                        }
                    }
                }
            }
        }

        // AI Insights
        if (insights?.aiInsights != null) {
            item {
                ElevatedCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.Insights, null, tint = MaterialTheme.colorScheme.secondary)
                            Spacer(Modifier.width(8.dp))
                            Text("AI Insights", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                        }
                        Spacer(Modifier.height(8.dp))
                        Text(insights!!.aiInsights!!, style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
        }
        item { Spacer(Modifier.height(80.dp)) }
    }
}

@Composable
private fun StatColumn(label: String, value: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleLarge)
        Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
