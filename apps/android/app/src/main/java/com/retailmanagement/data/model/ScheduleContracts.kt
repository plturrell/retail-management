package com.retailmanagement.data.model

import com.google.gson.annotations.SerializedName

// ── Manager Scheduling Contracts ──

data class ScheduleRead(
    val id: String,
    @SerializedName("store_id") val storeId: String,
    @SerializedName("week_start") val weekStart: String,
    val status: String,
    @SerializedName("created_by") val createdBy: String,
    @SerializedName("published_at") val publishedAt: String? = null,
    val shifts: List<ShiftRead> = emptyList(),
    @SerializedName("created_at") val createdAt: String? = null,
    @SerializedName("updated_at") val updatedAt: String? = null
)

data class DayShifts(
    val date: String,
    val shifts: List<ShiftRead>
)

data class WeeklyScheduleResponse(
    val schedule: ScheduleRead,
    val days: List<DayShifts>
)

data class ScheduleCreate(
    @SerializedName("store_id") val storeId: String,
    @SerializedName("week_start") val weekStart: String
)

data class ScheduleUpdate(
    val status: String
)

data class ShiftCreate(
    @SerializedName("user_id") val userId: String,
    @SerializedName("shift_date") val shiftDate: String,
    @SerializedName("start_time") val startTime: String,
    @SerializedName("end_time") val endTime: String,
    @SerializedName("break_minutes") val breakMinutes: Int = 60,
    val notes: String? = null
)

data class ShiftUpdate(
    @SerializedName("start_time") val startTime: String? = null,
    @SerializedName("end_time") val endTime: String? = null,
    @SerializedName("break_minutes") val breakMinutes: Int? = null,
    val notes: String? = null
)

// ── Timesheet Manager Contracts ──

data class TimeEntryUpdate(
    val status: String
)

data class TimesheetSummaryEntry(
    @SerializedName("user_id") val userId: String,
    @SerializedName("full_name") val fullName: String,
    @SerializedName("total_hours") val totalHours: Double,
    @SerializedName("total_days") val totalDays: Int,
    val entries: List<TimeEntryRead>
)

data class TimesheetSummaryResponse(
    @SerializedName("period_start") val periodStart: String,
    @SerializedName("period_end") val periodEnd: String,
    val summaries: List<TimesheetSummaryEntry>
)
