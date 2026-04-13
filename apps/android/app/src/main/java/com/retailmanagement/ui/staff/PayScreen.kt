package com.retailmanagement.ui.staff

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Receipt
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.retailmanagement.data.api.RetrofitClient
import com.retailmanagement.data.model.PaySlipRead
import com.retailmanagement.data.model.PayrollRunRead
import com.retailmanagement.data.model.PayrollRunSummary
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class PayViewModel : ViewModel() {
    private val _runs = MutableStateFlow<List<PayrollRunSummary>>(emptyList())
    val runs = _runs.asStateFlow()
    private val _selectedSlip = MutableStateFlow<PaySlipRead?>(null)
    val selectedSlip = _selectedSlip.asStateFlow()
    private val _isLoading = MutableStateFlow(false)
    val isLoading = _isLoading.asStateFlow()
    private val _error = MutableStateFlow<String?>(null)
    val error = _error.asStateFlow()
    private val _allSlips = MutableStateFlow<List<PaySlipRead>>(emptyList())
    val allSlips = _allSlips.asStateFlow()

    fun loadRuns(storeId: String, userId: String) {
        viewModelScope.launch {
            _isLoading.value = true
            try {
                val resp = RetrofitClient.api.listPayrollRuns(storeId)
                _runs.value = resp.data
                // Load payslips from each run for current user
                val slips = mutableListOf<PaySlipRead>()
                for (run in resp.data) {
                    try {
                        val detail = RetrofitClient.api.getPayrollRun(storeId, run.id)
                        slips.addAll(detail.data.payslips.filter { it.userId == userId })
                    } catch (_: Exception) { /* skip runs we can't access */ }
                }
                _allSlips.value = slips.sortedByDescending { it.createdAt }
            } catch (e: Exception) { _error.value = e.message }
            finally { _isLoading.value = false }
        }
    }

    fun selectSlip(slip: PaySlipRead?) { _selectedSlip.value = slip }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PayScreen(storeId: String, userId: String, vm: PayViewModel = viewModel()) {
    val slips by vm.allSlips.collectAsState()
    val selectedSlip by vm.selectedSlip.collectAsState()
    val isLoading by vm.isLoading.collectAsState()
    val error by vm.error.collectAsState()

    LaunchedEffect(storeId) { vm.loadRuns(storeId, userId) }

    if (selectedSlip != null) {
        PaySlipDetail(slip = selectedSlip!!, onBack = { vm.selectSlip(null) })
    } else {
        Column(Modifier.fillMaxSize()) {
            if (isLoading) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            } else if (error != null) {
                Box(Modifier.fillMaxSize().padding(16.dp), contentAlignment = Alignment.Center) {
                    Text(error!!, color = MaterialTheme.colorScheme.error)
                }
            } else if (slips.isEmpty()) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Icon(Icons.Default.Receipt, null, Modifier.size(48.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                        Spacer(Modifier.height(8.dp))
                        Text("No payslips yet", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            } else {
                LazyColumn(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(slips) { slip ->
                        Card(Modifier.fillMaxWidth().clickable { vm.selectSlip(slip) }) {
                            Row(Modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                                Column {
                                    Text("Payslip", fontWeight = FontWeight.Medium)
                                    Text(slip.createdAt?.take(10) ?: "–", style = MaterialTheme.typography.bodySmall)
                                }
                                Column(horizontalAlignment = Alignment.End) {
                                    Text("$${String.format("%.2f", slip.netPay)}", fontWeight = FontWeight.Bold,
                                        color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.titleMedium)
                                    Text("Net Pay", style = MaterialTheme.typography.bodySmall)
                                }
                            }
                        }
                    }
                    item { Spacer(Modifier.height(80.dp)) }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PaySlipDetail(slip: PaySlipRead, onBack: () -> Unit) {
    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("Payslip Detail") },
            navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.Default.ArrowBack, "Back") } }
        )
        LazyColumn(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            item { Text("Earnings", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold) }
            item { PayRow("Basic Salary", slip.basicSalary) }
            item { PayRow("Hours Worked", slip.hoursWorked ?: 0.0, isCurrency = false, suffix = "h") }
            item { PayRow("Overtime (${slip.overtimeHours}h)", slip.overtimePay) }
            item { PayRow("Commission (on $${String.format("%.2f", slip.commissionSales)})", slip.commissionAmount) }
            item { PayRow("Allowances", slip.allowances) }
            item { HorizontalDivider(Modifier.padding(vertical = 8.dp)) }
            item { PayRow("Gross Pay", slip.grossPay, bold = true) }
            item { Spacer(Modifier.height(12.dp)) }
            item { Text("Deductions", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold) }
            item { PayRow("CPF Employee", slip.cpfEmployee) }
            item { PayRow("CPF Employer", slip.cpfEmployer) }
            item { PayRow("Other Deductions", slip.deductions) }
            item { HorizontalDivider(Modifier.padding(vertical = 8.dp)) }
            item {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("Net Pay", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleMedium)
                    Text("$${String.format("%.2f", slip.netPay)}", fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.titleMedium)
                }
            }
            if (slip.notes != null) {
                item { Spacer(Modifier.height(12.dp)); Text("Notes: ${slip.notes}", style = MaterialTheme.typography.bodySmall) }
            }
        }
    }
}

@Composable
private fun PayRow(label: String, value: Double, bold: Boolean = false, isCurrency: Boolean = true, suffix: String = "") {
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, fontWeight = if (bold) FontWeight.Bold else FontWeight.Normal)
        val text = if (isCurrency) "$${String.format("%.2f", value)}" else "${String.format("%.1f", value)}$suffix"
        Text(text, fontWeight = if (bold) FontWeight.Bold else FontWeight.Normal)
    }
}
