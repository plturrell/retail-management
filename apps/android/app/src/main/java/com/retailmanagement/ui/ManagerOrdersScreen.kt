package com.retailmanagement.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
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

class ManagerOrdersViewModel : ViewModel() {

    private val api get() = RetrofitClient.api

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()

    private val _orders = MutableStateFlow<List<Order>>(emptyList())

    val searchQuery = MutableStateFlow("")
    val filterStatus = MutableStateFlow<OrderStatus?>(null)

    val filteredOrders: StateFlow<List<Order>>
        get() = _orders // computed via derivedStateOf in UI

    fun getFiltered(): List<Order> {
        val q = searchQuery.value.lowercase()
        val f = filterStatus.value
        return _orders.value.filter { order ->
            (f == null || order.orderStatus == f) &&
            (q.isBlank() || order.orderNumber.lowercase().contains(q) || order.paymentMethod.lowercase().contains(q))
        }
    }

    fun loadOrders(storeId: String) {
        viewModelScope.launch {
            _isLoading.value = true
            _error.value = null
            try {
                val res = api.listOrders(storeId, pageSize = 200)
                _orders.value = res.data
            } catch (e: Exception) {
                _error.value = e.message ?: "Failed to load orders"
            }
            _isLoading.value = false
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ManagerOrdersScreen(
    storeId: String,
    vm: ManagerOrdersViewModel = viewModel()
) {
    val isLoading by vm.isLoading.collectAsState()
    val error by vm.error.collectAsState()
    val searchQuery by vm.searchQuery.collectAsState()
    val filterStatus by vm.filterStatus.collectAsState()

    var selectedOrder by remember { mutableStateOf<Order?>(null) }

    // Derive filtered list reactively
    val displayOrders by remember { derivedStateOf { vm.getFiltered() } }

    LaunchedEffect(storeId) { vm.loadOrders(storeId) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Orders") },
                actions = {
                    IconButton(onClick = { vm.loadOrders(storeId) }) {
                        Icon(Icons.Default.Refresh, contentDescription = "Refresh")
                    }
                }
            )
        }
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {

            // Search bar
            OutlinedTextField(
                value = searchQuery,
                onValueChange = { vm.searchQuery.value = it },
                placeholder = { Text("Search orders…") },
                leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                shape = RoundedCornerShape(12.dp)
            )

            // Status filter chips
            Row(
                Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                FilterChipItem(label = "All", selected = filterStatus == null) {
                    vm.filterStatus.value = null
                }
                OrderStatus.entries.forEach { status ->
                    FilterChipItem(
                        label = status.display,
                        selected = filterStatus == status,
                        color = when (status) {
                            OrderStatus.COMPLETED -> MaterialTheme.colorScheme.secondary
                            OrderStatus.VOIDED    -> MaterialTheme.colorScheme.error
                            else                 -> MaterialTheme.colorScheme.primary
                        }
                    ) { vm.filterStatus.value = status }
                }
            }

            Spacer(Modifier.height(4.dp))

            when {
                isLoading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
                error != null -> Box(Modifier.fillMaxSize().padding(16.dp), contentAlignment = Alignment.Center) {
                    Text(error!!, color = MaterialTheme.colorScheme.error)
                }
                displayOrders.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text("No orders found.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                else -> {
                    Text(
                        "${displayOrders.size} orders",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)
                    )
                    LazyColumn(contentPadding = PaddingValues(horizontal = 16.dp, vertical = 4.dp)) {
                        items(displayOrders, key = { it.id }) { order ->
                            OrderListCard(order = order) { selectedOrder = order }
                            Spacer(Modifier.height(8.dp))
                        }
                    }
                }
            }
        }
    }

    // Detail bottom sheet
    selectedOrder?.let { order ->
        ModalBottomSheet(onDismissRequest = { selectedOrder = null }) {
            OrderDetailSheet(order = order)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FilterChipItem(
    label: String,
    selected: Boolean,
    color: Color = MaterialTheme.colorScheme.primary,
    onClick: () -> Unit
) {
    FilterChip(
        selected = selected,
        onClick = onClick,
        label = { Text(label, fontSize = 13.sp) },
        colors = FilterChipDefaults.filterChipColors(
            selectedContainerColor = color.copy(alpha = 0.12f),
            selectedLabelColor = color
        )
    )
}

@Composable
private fun OrderListCard(order: Order, onClick: () -> Unit) {
    val statusColor = when (order.orderStatus) {
        OrderStatus.COMPLETED -> Color(0xFF1E8A44)
        OrderStatus.VOIDED    -> MaterialTheme.colorScheme.error
        else                  -> MaterialTheme.colorScheme.primary
    }

    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        shape = RoundedCornerShape(12.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Text(
                    order.orderNumber,
                    fontWeight = FontWeight.Medium,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 13.sp
                )
                Surface(
                    color = statusColor.copy(alpha = 0.12f),
                    shape = RoundedCornerShape(20.dp)
                ) {
                    Text(
                        order.orderStatus.display,
                        color = statusColor,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 3.dp)
                    )
                }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(order.orderSource.display, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(order.paymentMethod, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("${order.itemCount} items", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(order.formattedTotal, fontWeight = FontWeight.Bold, fontSize = 15.sp)
            }
        }
    }
}

@Composable
private fun OrderDetailSheet(order: Order) {
    val statusColor = when (order.orderStatus) {
        OrderStatus.COMPLETED -> Color(0xFF1E8A44)
        OrderStatus.VOIDED    -> MaterialTheme.colorScheme.error
        else                  -> MaterialTheme.colorScheme.primary
    }

    Column(Modifier.padding(horizontal = 20.dp).padding(bottom = 32.dp)) {
        Text("Order Details", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(16.dp))

        // Order info
        Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = RoundedCornerShape(12.dp)) {
            Column(Modifier.padding(14.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                DetailRow("Order #", order.orderNumber)
                DetailRow("Status") {
                    Text(order.orderStatus.display, color = statusColor, fontWeight = FontWeight.Bold)
                }
                DetailRow("Source", order.orderSource.display)
                DetailRow("Date", order.orderDate.take(10))
                DetailRow("Payment", order.paymentMethod)
                order.paymentRef?.let { DetailRow("Reference", it) }
            }
        }

        Spacer(Modifier.height(16.dp))
        Text("Items (${order.items.size})", fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(8.dp))

        order.items.forEach { item ->
            Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                Column(Modifier.weight(1f)) {
                    Text(item.skuId, fontFamily = FontFamily.Monospace, fontSize = 13.sp)
                    Text("${item.qty} × ${String.format("$%.2f", item.unitPrice)}", fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Column(horizontalAlignment = Alignment.End) {
                    Text(String.format("$%.2f", item.lineTotal), fontWeight = FontWeight.Medium)
                    if (item.discount > 0) {
                        Text("-${String.format("$%.2f", item.discount)}", fontSize = 11.sp, color = Color(0xFF1E8A44))
                    }
                }
            }
            Divider()
        }

        Spacer(Modifier.height(12.dp))

        // Totals
        Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = RoundedCornerShape(12.dp)) {
            Column(Modifier.padding(14.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                DetailRow("Subtotal", String.format("$%.2f", order.subtotal))
                if (order.discountTotal > 0) DetailRow("Discount", "-${String.format("$%.2f", order.discountTotal)}")
                DetailRow("Tax", String.format("$%.2f", order.taxTotal))
                Divider()
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("Grand Total", fontWeight = FontWeight.Bold)
                    Text(order.formattedTotal, fontWeight = FontWeight.Bold, fontSize = 17.sp)
                }
            }
        }
    }
}

@Composable
private fun DetailRow(label: String, value: String? = null, valueContent: (@Composable () -> Unit)? = null) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 13.sp)
        if (valueContent != null) valueContent()
        else Text(value ?: "–", fontWeight = FontWeight.Medium, fontSize = 13.sp)
    }
}
