package com.retailmanagement.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.retailmanagement.data.api.RetrofitClient
import com.retailmanagement.data.model.*
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.*

class ManagerScheduleViewModel : ViewModel() {

    private val api get() = RetrofitClient.api

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading.asStateFlow()

    private val _isActionLoading = MutableStateFlow(false)
    val isActionLoading: StateFlow<Boolean> = _isActionLoading.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()

    private val _schedule = MutableStateFlow<ScheduleRead?>(null)
    val schedule: StateFlow<ScheduleRead?> = _schedule.asStateFlow()

    private val _shifts = MutableStateFlow<List<ShiftRead>>(emptyList())
    val shifts: StateFlow<List<ShiftRead>> = _shifts.asStateFlow()

    private val _employees = MutableStateFlow<List<StoreEmployeeRead>>(emptyList())
    val employees: StateFlow<List<StoreEmployeeRead>> = _employees.asStateFlow()

    private val _weekStart = MutableStateFlow(currentMonday())
    val weekStart: StateFlow<Date> = _weekStart.asStateFlow()

    private val isoFormat = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())

    fun currentMonday(): Date {
        val cal = Calendar.getInstance()
        cal.firstDayOfWeek = Calendar.MONDAY
        cal.set(Calendar.DAY_OF_WEEK, Calendar.MONDAY)
        cal.set(Calendar.HOUR_OF_DAY, 0); cal.set(Calendar.MINUTE, 0)
        cal.set(Calendar.SECOND, 0); cal.set(Calendar.MILLISECOND, 0)
        return cal.time
    }

    fun goToPreviousWeek() { _weekStart.value = Date(_weekStart.value.time - 7 * 86400_000L) }
    fun goToNextWeek() { _weekStart.value = Date(_weekStart.value.time + 7 * 86400_000L) }
    fun goToCurrentWeek() { _weekStart.value = currentMonday() }

    fun dayDates(): List<Date> = (0..6).map { Date(_weekStart.value.time + it * 86400_000L) }
    fun dateStr(d: Date): String = isoFormat.format(d)

    fun weekLabel(): String {
        val fmt = SimpleDateFormat("MMM d", Locale.getDefault())
        val end = Date(_weekStart.value.time + 6 * 86400_000L)
        return "${fmt.format(_weekStart.value)} – ${fmt.format(end)}"
    }

    fun loadData(storeId: String) {
        viewModelScope.launch {
            _isLoading.value = true
            _error.value = null
            try {
                val empDef = async { api.getStoreEmployees(storeId) }
                val schedDef = async { api.listSchedules(storeId, isoFormat.format(_weekStart.value)) }

                val empRes = empDef.await()
                val schedRes = schedDef.await()
                _employees.value = empRes.data

                val firstSched = schedRes.data.firstOrNull()
                if (firstSched != null) {
                    val detail = api.getSchedule(storeId, firstSched.id)
                    _schedule.value = detail.data.schedule
                    _shifts.value = detail.data.schedule.shifts
                } else {
                    _schedule.value = null
                    _shifts.value = emptyList()
                }
            } catch (e: Exception) {
                _error.value = e.message ?: "Unknown error"
            }
            _isLoading.value = false
        }
    }

    fun initializeSchedule(storeId: String) {
        viewModelScope.launch {
            _isActionLoading.value = true
            try {
                api.createSchedule(storeId, ScheduleCreate(storeId, isoFormat.format(_weekStart.value)))
                loadData(storeId)
            } catch (e: Exception) {
                _error.value = e.message
            }
            _isActionLoading.value = false
        }
    }

    fun togglePublishStatus(storeId: String) {
        val sched = _schedule.value ?: return
        viewModelScope.launch {
            _isActionLoading.value = true
            try {
                val newStatus = if (sched.status == "draft") "published" else "draft"
                api.updateSchedule(storeId, sched.id, ScheduleUpdate(newStatus))
                loadData(storeId)
            } catch (e: Exception) {
                _error.value = e.message
            }
            _isActionLoading.value = false
        }
    }

    fun saveShift(storeId: String, shiftId: String?, userId: String, date: String, startTime: String, endTime: String, breakMinutes: Int, notes: String?) {
        val sched = _schedule.value ?: return
        viewModelScope.launch {
            _isActionLoading.value = true
            try {
                if (shiftId != null) {
                    api.updateShift(storeId, sched.id, shiftId, ShiftUpdate(startTime, endTime, breakMinutes, notes))
                } else {
                    api.createShift(storeId, sched.id, ShiftCreate(userId, date, startTime, endTime, breakMinutes, notes))
                }
                loadData(storeId)
            } catch (e: Exception) {
                _error.value = e.message
            }
            _isActionLoading.value = false
        }
    }

    fun deleteShift(storeId: String, shiftId: String) {
        val sched = _schedule.value ?: return
        viewModelScope.launch {
            _isActionLoading.value = true
            try {
                api.deleteShift(storeId, sched.id, shiftId)
                loadData(storeId)
            } catch (e: Exception) {
                _error.value = e.message
            }
            _isActionLoading.value = false
        }
    }
}
