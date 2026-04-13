package com.retailmanagement.data.model

import com.google.gson.annotations.SerializedName
import java.math.BigDecimal

// ── Generic API wrappers ──

data class DataResponse<T>(
    val success: Boolean = true,
    val message: String = "OK",
    val data: T
)

data class PaginatedResponse<T>(
    val success: Boolean = true,
    val message: String = "OK",
    val data: List<T>,
    val total: Int,
    val page: Int,
    @SerializedName("page_size") val pageSize: Int
)

// ── Schedule / Shift ──

data class ShiftRead(
    val id: String,
    @SerializedName("schedule_id") val scheduleId: String,
    @SerializedName("user_id") val userId: String,
    @SerializedName("shift_date") val shiftDate: String,
    @SerializedName("start_time") val startTime: String,
    @SerializedName("end_time") val endTime: String,
    @SerializedName("break_minutes") val breakMinutes: Int = 60,
    val notes: String? = null,
    val hours: Double = 0.0,
    @SerializedName("created_at") val createdAt: String? = null
)

// ── Timesheet ──

data class ClockInRequest(
    @SerializedName("store_id") val storeId: String,
    val notes: String? = null
)

data class ClockOutRequest(
    @SerializedName("break_minutes") val breakMinutes: Int = 0,
    val notes: String? = null
)

data class TimeEntryRead(
    val id: String,
    @SerializedName("user_id") val userId: String,
    @SerializedName("store_id") val storeId: String,
    @SerializedName("clock_in") val clockIn: String,
    @SerializedName("clock_out") val clockOut: String? = null,
    @SerializedName("break_minutes") val breakMinutes: Int = 0,
    val notes: String? = null,
    val status: String,
    @SerializedName("approved_by") val approvedBy: String? = null,
    @SerializedName("hours_worked") val hoursWorked: Double? = null,
    @SerializedName("created_at") val createdAt: String? = null
)

// ── Payroll / Payslip ──

data class PaySlipRead(
    val id: String,
    @SerializedName("payroll_run_id") val payrollRunId: String,
    @SerializedName("user_id") val userId: String,
    @SerializedName("basic_salary") val basicSalary: Double,
    @SerializedName("hours_worked") val hoursWorked: Double? = null,
    @SerializedName("overtime_hours") val overtimeHours: Double = 0.0,
    @SerializedName("overtime_pay") val overtimePay: Double = 0.0,
    val allowances: Double = 0.0,
    val deductions: Double = 0.0,
    @SerializedName("commission_sales") val commissionSales: Double = 0.0,
    @SerializedName("commission_amount") val commissionAmount: Double = 0.0,
    @SerializedName("gross_pay") val grossPay: Double,
    @SerializedName("cpf_employee") val cpfEmployee: Double,
    @SerializedName("cpf_employer") val cpfEmployer: Double,
    @SerializedName("net_pay") val netPay: Double,
    val notes: String? = null,
    @SerializedName("created_at") val createdAt: String? = null
)

data class PayrollRunSummary(
    val id: String,
    @SerializedName("store_id") val storeId: String,
    @SerializedName("period_start") val periodStart: String,
    @SerializedName("period_end") val periodEnd: String,
    val status: String,
    @SerializedName("total_gross") val totalGross: Double,
    @SerializedName("total_net") val totalNet: Double,
    @SerializedName("created_at") val createdAt: String? = null
)

data class PayrollRunRead(
    val id: String,
    @SerializedName("store_id") val storeId: String,
    @SerializedName("period_start") val periodStart: String,
    @SerializedName("period_end") val periodEnd: String,
    val status: String,
    @SerializedName("total_gross") val totalGross: Double,
    @SerializedName("total_cpf_employee") val totalCpfEmployee: Double,
    @SerializedName("total_cpf_employer") val totalCpfEmployer: Double,
    @SerializedName("total_net") val totalNet: Double,
    val payslips: List<PaySlipRead> = emptyList()
)

// ── Staff Performance ──

data class StaffPerformanceItem(
    @SerializedName("user_id") val userId: String,
    @SerializedName("full_name") val fullName: String,
    @SerializedName("total_sales") val totalSales: Double,
    @SerializedName("order_count") val orderCount: Int,
    @SerializedName("avg_order_value") val avgOrderValue: Double,
    val rank: Int
)

data class StaffPerformanceOverview(
    @SerializedName("generated_at") val generatedAt: String,
    @SerializedName("store_id") val storeId: String,
    @SerializedName("period_from") val periodFrom: String,
    @SerializedName("period_to") val periodTo: String,
    val staff: List<StaffPerformanceItem>,
    @SerializedName("total_store_sales") val totalStoreSales: Double
)

data class StaffInsightsResponse(
    @SerializedName("user_id") val userId: String,
    @SerializedName("full_name") val fullName: String,
    val summary: Map<String, Any>? = null,
    @SerializedName("ai_insights") val aiInsights: String? = null
)

// ── User / Profile ──

data class UserRead(
    val id: String,
    val email: String,
    @SerializedName("full_name") val fullName: String,
    val phone: String? = null,
    @SerializedName("firebase_uid") val firebaseUid: String,
    @SerializedName("store_roles") val storeRoles: List<UserStoreRoleRead>? = null
)

data class UserStoreRoleRead(
    val id: String,
    @SerializedName("user_id") val userId: String,
    @SerializedName("store_id") val storeId: String,
    val role: String
)

data class EmployeeProfileRead(
    val id: String,
    @SerializedName("user_id") val userId: String,
    @SerializedName("date_of_birth") val dateOfBirth: String,
    val nationality: String,
    @SerializedName("basic_salary") val basicSalary: Double,
    @SerializedName("hourly_rate") val hourlyRate: Double? = null,
    @SerializedName("commission_rate") val commissionRate: Double? = null,
    @SerializedName("bank_name") val bankName: String,
    @SerializedName("start_date") val startDate: String,
    @SerializedName("end_date") val endDate: String? = null,
    @SerializedName("is_active") val isActive: Boolean
)
