package com.retailmanagement.ui.staff

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Login
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.Timer
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
import com.retailmanagement.data.model.ClockInRequest
import com.retailmanagement.data.model.ClockOutRequest
import com.retailmanagement.data.model.TimeEntryRead
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.time.Duration
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

class TimesheetViewModel : ViewModel() {
    private val _activeEntry = MutableStateFlow<TimeEntryRead?>(null)
    val activeEntry = _activeEntry.asStateFlow()
    private val _history = MutableStateFlow<List<TimeEntryRead>>(emptyList())
    val history = _history.asStateFlow()
    private val _isLoading = MutableStateFlow(false)
    val isLoading = _isLoading.asStateFlow()
    private val _error = MutableStateFlow<String?>(null)
    val error = _error.asStateFlow()
    private val _elapsed = MutableStateFlow(0L)
    val elapsed = _elapsed.asStateFlow()

    fun loadStatus(storeId: String, userId: String) {
        viewModelScope.launch {
            _isLoading.value = true
            try {
                val statusResp = RetrofitClient.api.getClockStatus()
                _activeEntry.value = statusResp.data
                val histResp = RetrofitClient.api.listTimesheets(storeId, userId)
                _history.value = histResp.data
            } catch (e: Exception) { _error.value = e.message }
            finally { _isLoading.value = false }
        }
    }

    fun startTimer() {
        viewModelScope.launch {
            while (_activeEntry.value != null) {
                val clockIn = _activeEntry.value?.clockIn ?: break
                try {
                    val start = Instant.parse(clockIn)
                    _elapsed.value = Duration.between(start, Instant.now()).seconds
                } catch (_: Exception) { /* ignore parse errors */ }
                delay(1000)
            }
        }
    }

    fun clockIn(storeId: String, userId: String) {
        viewModelScope.launch {
            _isLoading.value = true; _error.value = null
            try {
                val resp = RetrofitClient.api.clockIn(ClockInRequest(storeId))
                _activeEntry.value = resp.data
                startTimer(); loadStatus(storeId, userId)
            } catch (e: Exception) { _error.value = e.message }
            finally { _isLoading.value = false }
        }
    }

    fun clockOut(storeId: String, userId: String) {
        viewModelScope.launch {
            _isLoading.value = true; _error.value = null
            try {
                RetrofitClient.api.clockOut(ClockOutRequest())
                _activeEntry.value = null; _elapsed.value = 0
                loadStatus(storeId, userId)
            } catch (e: Exception) { _error.value = e.message }
            finally { _isLoading.value = false }
        }
    }
}

@Composable
fun TimesheetScreen(storeId: String, userId: String, vm: TimesheetViewModel = viewModel()) {
    val active by vm.activeEntry.collectAsState()
    val historyList by vm.history.collectAsState()
    val loading by vm.isLoading.collectAsState()
    val err by vm.error.collectAsState()
    val elapsed by vm.elapsed.collectAsState()
    LaunchedEffect(storeId) { vm.loadStatus(storeId, userId); vm.startTimer() }
    val isClockedIn = active != null
    val h = elapsed / 3600; val m = (elapsed % 3600) / 60; val s = elapsed % 60

    LazyColumn(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            ElevatedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.fillMaxWidth().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(Icons.Default.Timer, null, Modifier.size(48.dp),
                        tint = if (isClockedIn) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(12.dp))
                    if (isClockedIn) {
                        Text(String.format("%02d:%02d:%02d", h, m, s),
                            style = MaterialTheme.typography.displayMedium, fontWeight = FontWeight.Bold)
                        Text("Clocked in", color = MaterialTheme.colorScheme.primary)
                    } else {
                        Text("Not clocked in", style = MaterialTheme.typography.titleLarge,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    if (err != null) Text(err!!, color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 4.dp))
                    Spacer(Modifier.height(16.dp))
                    Button(
                        onClick = { if (isClockedIn) vm.clockOut(storeId, userId) else vm.clockIn(storeId, userId) },
                        enabled = !loading,
                        colors = if (isClockedIn) ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)
                                 else ButtonDefaults.buttonColors(),
                        modifier = Modifier.fillMaxWidth().height(48.dp)
                    ) {
                        Icon(if (isClockedIn) Icons.AutoMirrored.Filled.Logout else Icons.AutoMirrored.Filled.Login, null)
                        Spacer(Modifier.width(8.dp))
                        Text(if (isClockedIn) "Clock Out" else "Clock In")
                    }
                }
            }
        }
        item { Text("Recent Entries", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) }
        items(historyList) { entry ->
            val dateFmt = DateTimeFormatter.ofPattern("d MMM yyyy")
            val timeFmt = DateTimeFormatter.ofPattern("HH:mm")
            val inTime = try { Instant.parse(entry.clockIn).atZone(ZoneId.systemDefault()) } catch (_: Exception) { null }
            Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                Row(Modifier.fillMaxWidth().padding(12.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Column {
                        Text(inTime?.format(dateFmt) ?: entry.clockIn.take(10), fontWeight = FontWeight.Medium)
                        val outStr = if (entry.clockOut != null) {
                            val o = try { Instant.parse(entry.clockOut).atZone(ZoneId.systemDefault()) } catch (_: Exception) { null }
                            "  Out: ${o?.format(timeFmt) ?: "–"}"
                        } else " (open)"
                        Text("In: ${inTime?.format(timeFmt) ?: "–"}$outStr", style = MaterialTheme.typography.bodySmall)
                    }
                    Column(horizontalAlignment = Alignment.End) {
                        if (entry.hoursWorked != null) Text("${entry.hoursWorked}h", fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
                        AssistChip(onClick = {}, label = { Text(entry.status, style = MaterialTheme.typography.labelSmall) })
                    }
                }
            }
        }
        item { Spacer(Modifier.height(80.dp)) }
    }
}
