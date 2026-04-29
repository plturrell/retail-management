package com.retailmanagement.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.material3.TabRowDefaults.tabIndicatorOffset
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import java.text.SimpleDateFormat
import java.util.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ManagerTimesheetsScreen(
    storeId: String,
    vm: ManagerTimesheetsViewModel = viewModel()
) {
    val isLoading by vm.isLoading.collectAsState()
    val isActionLoading by vm.isActionLoading.collectAsState()
    val error by vm.error.collectAsState()
    val pendingEntries by vm.pendingEntries.collectAsState()
    val summary by vm.summary.collectAsState()
    val summaryLoading by vm.summaryLoading.collectAsState()

    var selectedTab by remember { mutableIntStateOf(0) }
    val tabs = listOf("Pending Reviews", "Payroll Summary")

    LaunchedEffect(storeId) { vm.loadPending(storeId) }

    Scaffold(
        topBar = {
            TopAppBar(title = { Text("Timesheet Approvals") })
        }
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            TabRow(
                selectedTabIndex = selectedTab,
                indicator = { tabPositions ->
                    Box(
                        Modifier
                            .tabIndicatorOffset(tabPositions[selectedTab])
                            .fillMaxWidth()
                            .height(3.dp)
                            .background(MaterialTheme.colorScheme.primary)
                    )
                }
            ) {
                tabs.forEachIndexed { i, title ->
                    Tab(
                        selected = selectedTab == i,
                        onClick = {
                            selectedTab = i
                            if (i == 0) vm.loadPending(storeId) else vm.loadSummary(storeId)
                        },
                        text = {
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                Text(title)
                                if (i == 0 && pendingEntries.isNotEmpty()) {
                                    Badge { Text("${pendingEntries.size}") }
                                }
                            }
                        }
                    )
                }
            }

            error?.let {
                Text(it, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(16.dp))
            }

            when (selectedTab) {
                0 -> PendingTab(storeId, vm, isLoading, isActionLoading, pendingEntries)
                1 -> SummaryTab(storeId, vm, summaryLoading, summary)
            }
        }
    }
}

@Composable
private fun PendingTab(
    storeId: String,
    vm: ManagerTimesheetsViewModel,
    isLoading: Boolean,
    isActionLoading: Boolean,
    entries: List<com.retailmanagement.data.model.TimeEntryRead>
) {
    val displayFmt = SimpleDateFormat("MMM d, HH:mm", Locale.getDefault())
    val isoFmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.getDefault())

    fun fmt(iso: String): String = try { displayFmt.format(isoFmt.parse(iso)!!) } catch (_: Exception) { iso }

    when {
        isLoading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            CircularProgressIndicator()
        }
        entries.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("All caught up!", style = MaterialTheme.typography.titleMedium)
                Text("No pending timesheets.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        else -> LazyColumn(
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            items(entries) { entry ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("ID: ${entry.userId.take(8)}…", fontWeight = FontWeight.Medium)
                            SuggestionChip(onClick = {}, label = { Text("Pending", fontSize = 11.sp) })
                        }
                        Divider()
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Column {
                                Text("Clock In", fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                Text(fmt(entry.clockIn), fontWeight = FontWeight.Medium)
                            }
                            Column(horizontalAlignment = Alignment.End) {
                                Text("Clock Out", fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                Text(entry.clockOut?.let { fmt(it) } ?: "Active", fontWeight = FontWeight.Medium)
                            }
                        }
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Column {
                                Text("Duration", fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                Text(entry.hoursWorked?.let { String.format("%.2f hrs", it) } ?: "–", fontWeight = FontWeight.Bold)
                            }
                            Column(horizontalAlignment = Alignment.End) {
                                Text("Break", fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                Text("${entry.breakMinutes} min")
                            }
                        }
                        entry.notes?.takeIf { it.isNotBlank() }?.let {
                            Surface(
                                color = MaterialTheme.colorScheme.surfaceVariant,
                                shape = MaterialTheme.shapes.small
                            ) {
                                Text("\"$it\"", Modifier.padding(8.dp), fontSize = 12.sp,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                        Divider()
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(
                                onClick = { vm.updateStatus(storeId, entry.id, "rejected") {} },
                                enabled = !isActionLoading,
                                modifier = Modifier.weight(1f),
                                colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error)
                            ) { Text("Reject") }
                            Button(
                                onClick = { vm.updateStatus(storeId, entry.id, "approved") {} },
                                enabled = !isActionLoading,
                                modifier = Modifier.weight(1f)
                            ) { Text("Approve") }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SummaryTab(
    storeId: String,
    vm: ManagerTimesheetsViewModel,
    summaryLoading: Boolean,
    summary: com.retailmanagement.data.model.TimesheetSummaryResponse?
) {
    val dateFmt = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
    val periodStart by vm.periodStart.collectAsState()
    val periodEnd by vm.periodEnd.collectAsState()

    Column(Modifier.fillMaxSize()) {
        // Date range row
        Card(Modifier.fillMaxWidth().padding(16.dp)) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("Period", style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text("${dateFmt.format(periodStart)} → ${dateFmt.format(periodEnd)}",
                    fontWeight = FontWeight.Medium)
                Button(
                    onClick = { vm.loadSummary(storeId) },
                    modifier = Modifier.align(Alignment.End)
                ) { Text("Apply") }
            }
        }

        when {
            summaryLoading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            summary == null || summary.summaries.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("No timesheet data for this period.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            else -> {
                // Header
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text("Employee", fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                    Text("Days", fontWeight = FontWeight.Bold, modifier = Modifier.width(48.dp))
                    Text("Hours", fontWeight = FontWeight.Bold, modifier = Modifier.width(64.dp))
                }
                Divider(Modifier.padding(horizontal = 16.dp))
                LazyColumn(
                    contentPadding = PaddingValues(horizontal = 16.dp, vertical = 4.dp),
                    verticalArrangement = Arrangement.spacedBy(2.dp)
                ) {
                    items(summary.summaries) { s ->
                        Row(
                            Modifier.fillMaxWidth().padding(vertical = 10.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(s.fullName, modifier = Modifier.weight(1f))
                            Text("${s.totalDays}", modifier = Modifier.width(48.dp))
                            Text(String.format("%.2f", s.totalHours),
                                fontWeight = FontWeight.Bold, modifier = Modifier.width(64.dp))
                        }
                        Divider()
                    }
                    // Totals row
                    item {
                        val totalDays = summary.summaries.sumOf { it.totalDays }
                        val totalHours = summary.summaries.sumOf { it.totalHours }
                        Row(
                            Modifier.fillMaxWidth().padding(vertical = 12.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text("Total", fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                            Text("$totalDays", fontWeight = FontWeight.Bold, modifier = Modifier.width(48.dp))
                            Text(String.format("%.2f", totalHours),
                                fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.width(64.dp))
                        }
                    }
                }
            }
        }
    }
}
