package com.retailmanagement.data.api

import com.retailmanagement.data.model.*
import retrofit2.http.*

interface ApiService {

    // ── Auth / User ──

    @GET("api/users/me")
    suspend fun getMe(): DataResponse<UserRead>

    @GET("api/employees/{userId}/profile")
    suspend fun getEmployeeProfile(
        @Path("userId") userId: String
    ): DataResponse<EmployeeProfileRead>

    // ── Schedules ──

    @GET("api/stores/{storeId}/schedules/my-shifts")
    suspend fun getMyShifts(
        @Path("storeId") storeId: String,
        @Query("from") from: String,
        @Query("to") to: String
    ): DataResponse<List<ShiftRead>>

    // ── Timesheets ──

    @POST("api/timesheets/clock-in")
    suspend fun clockIn(
        @Body request: ClockInRequest
    ): DataResponse<TimeEntryRead>

    @POST("api/timesheets/clock-out")
    suspend fun clockOut(
        @Body request: ClockOutRequest
    ): DataResponse<TimeEntryRead>

    @GET("api/timesheets/status")
    suspend fun getClockStatus(): DataResponse<TimeEntryRead?>

    @GET("api/stores/{storeId}/timesheets")
    suspend fun listTimesheets(
        @Path("storeId") storeId: String,
        @Query("user_id") userId: String? = null,
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 20
    ): PaginatedResponse<TimeEntryRead>

    // ── Payroll ──

    @GET("api/stores/{storeId}/payroll")
    suspend fun listPayrollRuns(
        @Path("storeId") storeId: String
    ): DataResponse<List<PayrollRunSummary>>

    @GET("api/stores/{storeId}/payroll/{runId}")
    suspend fun getPayrollRun(
        @Path("storeId") storeId: String,
        @Path("runId") runId: String
    ): DataResponse<PayrollRunRead>

    // ── Sales / Performance ──

    @GET("api/stores/{storeId}/analytics/staff-performance")
    suspend fun getStaffPerformance(
        @Path("storeId") storeId: String,
        @Query("from") from: String,
        @Query("to") to: String
    ): StaffPerformanceOverview

    @GET("api/stores/{storeId}/analytics/staff/{userId}/insights")
    suspend fun getStaffInsights(
        @Path("storeId") storeId: String,
        @Path("userId") userId: String
    ): StaffInsightsResponse
}
