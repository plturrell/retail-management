package com.retailmanagement.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.retailmanagement.data.api.RetrofitClient
import com.retailmanagement.data.model.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.*

class ManagerTimesheetsViewModel : ViewModel() {

    private val api get() = RetrofitClient.api

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading.asStateFlow()

    private val _isActionLoading = MutableStateFlow(false)
    val isActionLoading: StateFlow<Boolean> = _isActionLoading.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()

    private val _pendingEntries = MutableStateFlow<List<TimeEntryRead>>(emptyList())
    val pendingEntries: StateFlow<List<TimeEntryRead>> = _pendingEntries.asStateFlow()

    private val _summary = MutableStateFlow<TimesheetSummaryResponse?>(null)
    val summary: StateFlow<TimesheetSummaryResponse?> = _summary.asStateFlow()

    private val _summaryLoading = MutableStateFlow(false)
    val summaryLoading: StateFlow<Boolean> = _summaryLoading.asStateFlow()

    // Default period: current month
    private val cal = Calendar.getInstance()
    val periodStart = MutableStateFlow(startOfMonth())
    val periodEnd = MutableStateFlow(endOfMonth())

    private val isoFmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.getDefault()).also {
        it.timeZone = TimeZone.getTimeZone("UTC")
    }
    private val dateFmt = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())

    private fun startOfMonth(): Date {
        cal.set(Calendar.DAY_OF_MONTH, 1)
        cal.set(Calendar.HOUR_OF_DAY, 0); cal.set(Calendar.MINUTE, 0)
        cal.set(Calendar.SECOND, 0); cal.set(Calendar.MILLISECOND, 0)
        return cal.time
    }

    private fun endOfMonth(): Date {
        cal.set(Calendar.DAY_OF_MONTH, cal.getActualMaximum(Calendar.DAY_OF_MONTH))
        cal.set(Calendar.HOUR_OF_DAY, 23); cal.set(Calendar.MINUTE, 59); cal.set(Calendar.SECOND, 59)
        return cal.time
    }

    fun loadPending(storeId: String) {
        viewModelScope.launch {
            _isLoading.value = true
            _error.value = null
            try {
                val res = api.listTimesheets(storeId, status = "pending", pageSize = 100)
                _pendingEntries.value = res.data.filter { it.clockOut != null }
            } catch (e: Exception) {
                _error.value = e.message
            }
            _isLoading.value = false
        }
    }

    fun loadSummary(storeId: String) {
        viewModelScope.launch {
            _summaryLoading.value = true
            _error.value = null
            try {
                val res = api.getTimesheetSummary(
                    storeId,
                    isoFmt.format(periodStart.value),
                    isoFmt.format(periodEnd.value)
                )
                _summary.value = res.data
            } catch (e: Exception) {
                _error.value = e.message
            }
            _summaryLoading.value = false
        }
    }

    fun updateStatus(storeId: String, entryId: String, status: String, onComplete: () -> Unit) {
        viewModelScope.launch {
            _isActionLoading.value = true
            try {
                api.updateTimesheetEntry(storeId, entryId, TimeEntryUpdate(status))
                loadPending(storeId)
                onComplete()
            } catch (e: Exception) {
                _error.value = e.message
            }
            _isActionLoading.value = false
        }
    }
}
