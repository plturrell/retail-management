package com.retailmanagement.ui

import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.lifecycle.viewmodel.compose.viewModel
import com.retailmanagement.data.model.ShiftRead
import java.text.SimpleDateFormat
import java.util.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ManagerScheduleScreen(
    storeId: String,
    vm: ManagerScheduleViewModel = viewModel()
) {
    val isLoading by vm.isLoading.collectAsState()
    val isActionLoading by vm.isActionLoading.collectAsState()
    val error by vm.error.collectAsState()
    val schedule by vm.schedule.collectAsState()
    val shifts by vm.shifts.collectAsState()
    val employees by vm.employees.collectAsState()
    val weekStart by vm.weekStart.collectAsState()

    var showShiftDialog by remember { mutableStateOf(false) }
    var selectedEmployeeId by remember { mutableStateOf("") }
    var selectedDateStr by remember { mutableStateOf("") }
    var shiftToEdit by remember { mutableStateOf<ShiftRead?>(null) }

    val dayDates = vm.dayDates()
    val dayFmt = SimpleDateFormat("EEE\ndd", Locale.getDefault())
    val today = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date())

    LaunchedEffect(storeId, weekStart) { vm.loadData(storeId) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Team Schedule") },
                actions = {
                    schedule?.let { sched ->
                        TextButton(
                            onClick = { vm.togglePublishStatus(storeId) },
                            enabled = !isActionLoading
                        ) {
                            Text(if (sched.status == "published") "Revert to Draft" else "Publish")
                        }
                    }
                }
            )
        }
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            // Week Nav Bar
            Row(
                Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceVariant).padding(8.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                IconButton(onClick = { vm.goToPreviousWeek(); vm.loadData(storeId) }) {
                    Icon(Icons.Default.ChevronLeft, contentDescription = "Previous week")
                }
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(vm.weekLabel(), fontWeight = FontWeight.Bold)
                    TextButton(onClick = { vm.goToCurrentWeek(); vm.loadData(storeId) }) {
                        Text("Current Week", fontSize = 12.sp)
                    }
                }
                IconButton(onClick = { vm.goToNextWeek(); vm.loadData(storeId) }) {
                    Icon(Icons.Default.ChevronRight, contentDescription = "Next week")
                }
            }

            when {
                isLoading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
                error != null -> Box(Modifier.fillMaxSize().padding(16.dp), contentAlignment = Alignment.Center) {
                    Text(error!!, color = MaterialTheme.colorScheme.error)
                }
                schedule == null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(16.dp)) {
                        Icon(Icons.Default.CalendarMonth, contentDescription = null,
                            modifier = Modifier.size(64.dp), tint = MaterialTheme.colorScheme.primary)
                        Text("No schedule for this week", style = MaterialTheme.typography.titleMedium)
                        Button(onClick = { vm.initializeSchedule(storeId) }, enabled = !isActionLoading) {
                            Text("Initialize Schedule")
                        }
                    }
                }
                else -> {
                    // Schedule Grid
                    Row(Modifier.fillMaxSize().horizontalScroll(rememberScrollState())) {
                        // Employee name column
                        Column(Modifier.width(130.dp)) {
                            // Header spacer
                            Box(
                                Modifier.height(64.dp).fillMaxWidth()
                                    .background(MaterialTheme.colorScheme.surfaceVariant)
                            ) {}
                            Divider()
                            employees.forEach { emp ->
                                Column(
                                    Modifier.height(70.dp).fillMaxWidth()
                                        .padding(horizontal = 8.dp, vertical = 4.dp),
                                    verticalArrangement = Arrangement.Center
                                ) {
                                    Text(emp.fullName, fontWeight = FontWeight.Medium, fontSize = 13.sp, maxLines = 1)
                                    Text(emp.role.replaceFirstChar { it.uppercase() },
                                        fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                                Divider()
                            }
                        }
                        Divider(modifier = Modifier.fillMaxHeight().width(1.dp))
                        // Day columns
                        dayDates.forEach { day ->
                            val dStr = vm.dateStr(day)
                            val isToday = dStr == today
                            Column(Modifier.width(120.dp)) {
                                // Day header
                                Box(
                                    Modifier.height(64.dp).fillMaxWidth()
                                        .background(if (isToday) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant),
                                    contentAlignment = Alignment.Center
                                ) {
                                    Text(
                                        dayFmt.format(day),
                                        fontSize = 12.sp,
                                        fontWeight = FontWeight.Bold,
                                        color = if (isToday) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                                        lineHeight = 16.sp
                                    )
                                }
                                Divider()
                                employees.forEach { emp ->
                                    val shift = shifts.find { it.userId == emp.id && it.shiftDate == dStr }
                                    Box(
                                        Modifier.height(70.dp).fillMaxWidth()
                                            .padding(3.dp)
                                            .clickable {
                                                selectedEmployeeId = emp.id
                                                selectedDateStr = dStr
                                                shiftToEdit = shift
                                                showShiftDialog = true
                                            }
                                    ) {
                                        if (shift != null) {
                                            val isDraft = schedule?.status == "draft"
                                            Card(
                                                Modifier.fillMaxSize(),
                                                colors = CardDefaults.cardColors(
                                                    containerColor = if (isDraft) MaterialTheme.colorScheme.tertiaryContainer
                                                    else MaterialTheme.colorScheme.secondaryContainer
                                                ),
                                                shape = RoundedCornerShape(6.dp)
                                            ) {
                                                Column(Modifier.padding(4.dp)) {
                                                    val t = "${shift.startTime.take(5)}–${shift.endTime.take(5)}"
                                                    Text(t, fontSize = 11.sp, fontWeight = FontWeight.Bold, maxLines = 1)
                                                    Text("${String.format("%.1f", shift.hours)}h", fontSize = 10.sp,
                                                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                                                }
                                            }
                                        } else {
                                            Box(
                                                Modifier.fillMaxSize()
                                                    .border(1.dp, MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(6.dp)),
                                                contentAlignment = Alignment.Center
                                            ) {
                                                Icon(Icons.Default.Add, contentDescription = "Add shift",
                                                    tint = MaterialTheme.colorScheme.outlineVariant, modifier = Modifier.size(20.dp))
                                            }
                                        }
                                    }
                                    Divider()
                                }
                            }
                            Divider(modifier = Modifier.fillMaxHeight().width(1.dp))
                        }
                    }
                }
            }
        }
    }

    // Shift editor dialog
    if (showShiftDialog) {
        ShiftEditorDialog(
            employeeName = employees.find { it.id == selectedEmployeeId }?.fullName ?: "",
            dateStr = selectedDateStr,
            existingShift = shiftToEdit,
            onDismiss = { showShiftDialog = false },
            onSave = { start, end, breakMin, notes ->
                vm.saveShift(storeId, shiftToEdit?.id, selectedEmployeeId, selectedDateStr, start, end, breakMin, notes)
                showShiftDialog = false
            },
            onDelete = {
                shiftToEdit?.id?.let { vm.deleteShift(storeId, it) }
                showShiftDialog = false
            }
        )
    }
}

@Composable
fun ShiftEditorDialog(
    employeeName: String,
    dateStr: String,
    existingShift: ShiftRead?,
    onDismiss: () -> Unit,
    onSave: (start: String, end: String, breakMin: Int, notes: String?) -> Unit,
    onDelete: () -> Unit
) {
    var startTime by remember { mutableStateOf(existingShift?.startTime?.take(5) ?: "09:00") }
    var endTime by remember { mutableStateOf(existingShift?.endTime?.take(5) ?: "17:00") }
    var breakMinutes by remember { mutableStateOf((existingShift?.breakMinutes ?: 60).toString()) }
    var notes by remember { mutableStateOf(existingShift?.notes ?: "") }

    Dialog(onDismissRequest = onDismiss) {
        Card(shape = RoundedCornerShape(16.dp)) {
            Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(
                    if (existingShift == null) "Add Shift" else "Edit Shift",
                    style = MaterialTheme.typography.titleLarge
                )
                Text("$dateStr · $employeeName", style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                Divider()

                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    OutlinedTextField(
                        value = startTime,
                        onValueChange = { startTime = it },
                        label = { Text("Start") },
                        modifier = Modifier.weight(1f),
                        singleLine = true,
                        placeholder = { Text("09:00") }
                    )
                    OutlinedTextField(
                        value = endTime,
                        onValueChange = { endTime = it },
                        label = { Text("End") },
                        modifier = Modifier.weight(1f),
                        singleLine = true,
                        placeholder = { Text("17:00") }
                    )
                }
                OutlinedTextField(
                    value = breakMinutes,
                    onValueChange = { breakMinutes = it },
                    label = { Text("Break (mins)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = notes,
                    onValueChange = { notes = it },
                    label = { Text("Notes (optional)") },
                    modifier = Modifier.fillMaxWidth()
                )
                Divider()
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    if (existingShift != null) {
                        TextButton(onClick = onDelete, colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error)) {
                            Text("Delete")
                        }
                    } else {
                        Spacer(Modifier.width(1.dp))
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        TextButton(onClick = onDismiss) { Text("Cancel") }
                        Button(onClick = {
                            val b = breakMinutes.toIntOrNull() ?: 60
                            onSave("$startTime:00", "$endTime:00", b, notes.ifBlank { null })
                        }) {
                            Text("Save")
                        }
                    }
                }
            }
        }
    }
}
