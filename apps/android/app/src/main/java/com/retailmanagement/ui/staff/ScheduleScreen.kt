package com.retailmanagement.ui.staff

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronLeft
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Schedule
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
import com.retailmanagement.data.model.ShiftRead
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.temporal.TemporalAdjusters

class ScheduleViewModel : ViewModel() {
    private val _shifts = MutableStateFlow<List<ShiftRead>>(emptyList())
    val shifts = _shifts.asStateFlow()
    private val _isLoading = MutableStateFlow(false)
    val isLoading = _isLoading.asStateFlow()
    private val _error = MutableStateFlow<String?>(null)
    val error = _error.asStateFlow()
    private val _weekStart = MutableStateFlow(
        LocalDate.now().with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
    )
    val weekStart = _weekStart.asStateFlow()

    fun loadShifts(storeId: String) {
        viewModelScope.launch {
            _isLoading.value = true
            _error.value = null
            try {
                val from = _weekStart.value.format(DateTimeFormatter.ISO_LOCAL_DATE)
                val to = _weekStart.value.plusDays(6).format(DateTimeFormatter.ISO_LOCAL_DATE)
                val response = RetrofitClient.api.getMyShifts(storeId, from, to)
                _shifts.value = response.data
            } catch (e: Exception) {
                _error.value = e.message ?: "Failed to load shifts"
            } finally {
                _isLoading.value = false
            }
        }
    }

    fun previousWeek(storeId: String) {
        _weekStart.value = _weekStart.value.minusWeeks(1)
        loadShifts(storeId)
    }

    fun nextWeek(storeId: String) {
        _weekStart.value = _weekStart.value.plusWeeks(1)
        loadShifts(storeId)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ScheduleScreen(storeId: String, viewModel: ScheduleViewModel = viewModel()) {
    val shifts by viewModel.shifts.collectAsState()
    val isLoading by viewModel.isLoading.collectAsState()
    val error by viewModel.error.collectAsState()
    val weekStart by viewModel.weekStart.collectAsState()

    LaunchedEffect(storeId) { viewModel.loadShifts(storeId) }

    val weekEnd = weekStart.plusDays(6)
    val fmt = DateTimeFormatter.ofPattern("d MMM")

    Column(modifier = Modifier.fillMaxSize()) {
        // Week navigator
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            IconButton(onClick = { viewModel.previousWeek(storeId) }) {
                Icon(Icons.Default.ChevronLeft, "Previous week")
            }
            Text(
                "${weekStart.format(fmt)} – ${weekEnd.format(fmt)}",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold
            )
            IconButton(onClick = { viewModel.nextWeek(storeId) }) {
                Icon(Icons.Default.ChevronRight, "Next week")
            }
        }

        if (isLoading) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
        } else if (error != null) {
            Box(Modifier.fillMaxSize().padding(16.dp), contentAlignment = Alignment.Center) {
                Text(error!!, color = MaterialTheme.colorScheme.error)
            }
        } else if (shifts.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(Icons.Default.Schedule, null, Modifier.size(48.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(8.dp))
                    Text("No shifts this week", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        } else {
            // Group by date
            val grouped = shifts.groupBy { it.shiftDate }.toSortedMap()
            LazyColumn(modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
                grouped.forEach { (date, dayShifts) ->
                    item {
                        val ld = LocalDate.parse(date)
                        Text(
                            ld.format(DateTimeFormatter.ofPattern("EEEE, d MMM")),
                            style = MaterialTheme.typography.labelLarge,
                            fontWeight = FontWeight.Bold,
                            modifier = Modifier.padding(top = 16.dp, bottom = 4.dp)
                        )
                    }
                    items(dayShifts) { shift ->
                        ShiftCard(shift)
                    }
                }
                item { Spacer(Modifier.height(80.dp)) }
            }
        }
    }
}

@Composable
fun ShiftCard(shift: ShiftRead) {
    Card(
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column {
                Text("${shift.startTime} – ${shift.endTime}", fontWeight = FontWeight.Medium)
                if (shift.notes != null) {
                    Text(shift.notes, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            Column(horizontalAlignment = Alignment.End) {
                Text("${shift.hours}h", fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
                Text("${shift.breakMinutes}m break", style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}
