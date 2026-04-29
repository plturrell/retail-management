package com.retailmanagement.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.CreditCard
import androidx.compose.material.icons.filled.Discount
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Receipt
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.retailmanagement.data.api.RetrofitClient
import com.retailmanagement.data.model.Order
import com.retailmanagement.data.model.OrderStatus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.*

// ── ViewModel ──

data class FinancialSummary(
    val totalRevenue: Double,
    val totalOrders: Int,
    val averageOrderValue: Double,
    val topPaymentMethod: String,
    val completedOrders: Int,
    val voidedOrders: Int,
    val discountsGiven: Double,
    val taxCollected: Double
)

data class DailyRevenue(val day: String, val amount: Double)

class FinancialsViewModel : ViewModel() {

    private val api get() = RetrofitClient.api

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()

    private val _summary = MutableStateFlow<FinancialSummary?>(null)
    val summary: StateFlow<FinancialSummary?> = _summary.asStateFlow()

    private val _daily = MutableStateFlow<List<DailyRevenue>>(emptyList())
    val daily: StateFlow<List<DailyRevenue>> = _daily.asStateFlow()

    fun loadFinancials(storeId: String) {
        viewModelScope.launch {
            _isLoading.value = true
            _error.value = null
            try {
                val res = api.listOrders(storeId, pageSize = 500)
                val orders: List<Order> = res.data
                val completed = orders.filter { it.orderStatus == OrderStatus.COMPLETED }

                val totalRevenue = completed.sumOf { it.grandTotal }
                val totalOrders = orders.size
                val avg = if (completed.isNotEmpty()) totalRevenue / completed.size else 0.0

                val paymentCounts = mutableMapOf<String, Int>()
                completed.forEach { paymentCounts[it.paymentMethod] = (paymentCounts[it.paymentMethod] ?: 0) + 1 }
                val topPayment = paymentCounts.maxByOrNull { it.value }?.key ?: "—"

                _summary.value = FinancialSummary(
                    totalRevenue = totalRevenue,
                    totalOrders = totalOrders,
                    averageOrderValue = avg,
                    topPaymentMethod = topPayment,
                    completedOrders = completed.size,
                    voidedOrders = orders.count { it.orderStatus == OrderStatus.VOIDED },
                    discountsGiven = orders.sumOf { it.discountTotal },
                    taxCollected = completed.sumOf { it.taxTotal }
                )

                // Build daily revenue
                val parseFmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.getDefault())
                val displayFmt = SimpleDateFormat("MMM d", Locale.getDefault())
                val daily = mutableMapOf<String, Double>()
                completed.forEach { order ->
                    try {
                        val date = parseFmt.parse(order.orderDate) ?: return@forEach
                        val key = displayFmt.format(date)
                        daily[key] = (daily[key] ?: 0.0) + order.grandTotal
                    } catch (_: Exception) {}
                }
                _daily.value = daily.entries
                    .sortedBy { it.key }
                    .takeLast(7)
                    .map { DailyRevenue(it.key, it.value) }

            } catch (e: Exception) {
                _error.value = e.message ?: "Failed to load financials"
            }
            _isLoading.value = false
        }
    }
}

// ── Screen ──

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FinancialsScreen(
    storeId: String,
    vm: FinancialsViewModel = viewModel()
) {
    val isLoading by vm.isLoading.collectAsState()
    val error by vm.error.collectAsState()
    val summary by vm.summary.collectAsState()
    val daily by vm.daily.collectAsState()

    LaunchedEffect(storeId) { vm.loadFinancials(storeId) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Financials") },
                actions = {
                    IconButton(onClick = { vm.loadFinancials(storeId) }) {
                        Icon(Icons.Default.Refresh, contentDescription = "Refresh")
                    }
                }
            )
        }
    ) { padding ->
        when {
            isLoading -> Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            error != null -> Box(Modifier.fillMaxSize().padding(padding).padding(16.dp), contentAlignment = Alignment.Center) {
                Text(error!!, color = MaterialTheme.colorScheme.error)
            }
            summary == null -> Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                Text("No financial data available.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            else -> {
                val s = summary!!
                Column(
                    Modifier
                        .fillMaxSize()
                        .padding(padding)
                        .verticalScroll(rememberScrollState())
                        .padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(16.dp)
                ) {
                    // Hero revenue card
                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        colors = CardDefaults.cardColors(containerColor = Color(0xFF1E8A44).copy(alpha = 0.08f)),
                        shape = RoundedCornerShape(16.dp)
                    ) {
                        Column(
                            Modifier.fillMaxWidth().padding(vertical = 24.dp, horizontal = 16.dp),
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            Text("Total Revenue", color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 14.sp)
                            Text(
                                String.format("$%.2f", s.totalRevenue),
                                fontSize = 36.sp,
                                fontWeight = FontWeight.Bold,
                                color = Color(0xFF1E8A44)
                            )
                            Text(
                                "${s.totalOrders} orders · Avg ${String.format("$%.2f", s.averageOrderValue)}",
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                fontSize = 12.sp
                            )
                        }
                    }

                    // Daily revenue chart
                    if (daily.isNotEmpty()) {
                        Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(16.dp)) {
                            Column(Modifier.padding(16.dp)) {
                                Text("Daily Revenue (Last 7 Days)", fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                                Spacer(Modifier.height(12.dp))
                                RevenueBarChart(data = daily, modifier = Modifier.fillMaxWidth().height(160.dp))
                                Spacer(Modifier.height(8.dp))
                                // Day labels
                                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                    daily.forEach { entry ->
                                        Text(entry.day, fontSize = 9.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    }
                                }
                            }
                        }
                    }

                    // Metric cards grid
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        FinancialMetricCard(
                            modifier = Modifier.weight(1f),
                            icon = Icons.Default.CheckCircle,
                            iconColor = Color(0xFF1E8A44),
                            title = "Completed",
                            value = "${s.completedOrders}"
                        )
                        FinancialMetricCard(
                            modifier = Modifier.weight(1f),
                            icon = Icons.Default.Receipt,
                            iconColor = MaterialTheme.colorScheme.error,
                            title = "Voided",
                            value = "${s.voidedOrders}"
                        )
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        FinancialMetricCard(
                            modifier = Modifier.weight(1f),
                            icon = Icons.Default.Discount,
                            iconColor = Color(0xFFE65100),
                            title = "Discounts",
                            value = String.format("$%.2f", s.discountsGiven)
                        )
                        FinancialMetricCard(
                            modifier = Modifier.weight(1f),
                            icon = Icons.Default.CreditCard,
                            iconColor = MaterialTheme.colorScheme.primary,
                            title = "Tax Collected",
                            value = String.format("$%.2f", s.taxCollected)
                        )
                    }

                    // Top payment method
                    Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp)) {
                        Row(
                            Modifier.fillMaxWidth().padding(16.dp),
                            horizontalArrangement = Arrangement.spacedBy(12.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(Icons.Default.CreditCard, contentDescription = null,
                                tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(28.dp))
                            Column {
                                Text("Top Payment Method", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                Text(s.topPaymentMethod, fontWeight = FontWeight.Bold, fontSize = 15.sp)
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun RevenueBarChart(data: List<DailyRevenue>, modifier: Modifier = Modifier) {
    val barColor = MaterialTheme.colorScheme.primary
    val maxAmount = data.maxOfOrNull { it.amount } ?: 1.0

    Canvas(modifier = modifier) {
        val barWidth = (size.width - (data.size - 1) * 8.dp.toPx()) / data.size
        val maxHeight = size.height - 20.dp.toPx()

        data.forEachIndexed { i, entry ->
            val barHeight = (entry.amount / maxAmount * maxHeight).toFloat().coerceAtLeast(4.dp.toPx())
            val left = i * (barWidth + 8.dp.toPx())
            val top = size.height - barHeight

            drawRoundRect(
                color = barColor,
                topLeft = Offset(left, top),
                size = Size(barWidth, barHeight),
                cornerRadius = CornerRadius(6.dp.toPx())
            )
        }
    }
}

@Composable
private fun FinancialMetricCard(
    modifier: Modifier = Modifier,
    icon: ImageVector,
    iconColor: Color,
    title: String,
    value: String
) {
    Card(
        modifier = modifier,
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = iconColor.copy(alpha = 0.06f))
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Icon(icon, contentDescription = null, tint = iconColor, modifier = Modifier.size(22.dp))
            Text(value, fontWeight = FontWeight.Bold, fontSize = 17.sp)
            Text(title, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
