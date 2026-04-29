package com.retailmanagement.data.api

import com.retailmanagement.data.model.*
import okhttp3.MultipartBody
import retrofit2.http.*

interface ApiService {

    // ── Auth / User ──

    @GET("api/users/me")
    suspend fun getMe(): DataResponse<UserRead>

    @GET("api/employees/{userId}/profile")
    suspend fun getEmployeeProfile(
        @Path("userId") userId: String
    ): DataResponse<EmployeeProfileRead>

    @GET("api/users/stores/{storeId}/employees")
    suspend fun getStoreEmployees(
        @Path("storeId") storeId: String
    ): PaginatedResponse<StoreEmployeeRead>

    @GET("api/users/search")
    suspend fun searchUsers(
        @Query("email") email: String
    ): DataResponse<List<SearchedUser>>

    @POST("api/users/roles")
    suspend fun assignUserRole(
        @Body request: UserStoreRoleCreate
    ): DataResponse<UserStoreRoleRead>

    @PATCH("api/users/roles/{roleId}")
    suspend fun updateUserRole(
        @Path("roleId") roleId: String,
        @Body request: UserStoreRoleUpdate
    ): DataResponse<UserStoreRoleRead>

    @DELETE("api/users/roles/{roleId}")
    suspend fun removeUserRole(
        @Path("roleId") roleId: String
    )

    // ── Schedules ──

    @GET("api/stores/{storeId}/schedules/my-shifts")
    suspend fun getMyShifts(
        @Path("storeId") storeId: String,
        @Query("from") from: String,
        @Query("to") to: String
    ): DataResponse<List<ShiftRead>>

    @GET("api/stores/{storeId}/schedules")
    suspend fun listSchedules(
        @Path("storeId") storeId: String,
        @Query("week_start") weekStart: String? = null
    ): PaginatedResponse<ScheduleRead>

    @GET("api/stores/{storeId}/schedules/{scheduleId}")
    suspend fun getSchedule(
        @Path("storeId") storeId: String,
        @Path("scheduleId") scheduleId: String
    ): DataResponse<WeeklyScheduleResponse>

    @POST("api/stores/{storeId}/schedules")
    suspend fun createSchedule(
        @Path("storeId") storeId: String,
        @Body request: ScheduleCreate
    ): DataResponse<ScheduleRead>

    @PATCH("api/stores/{storeId}/schedules/{scheduleId}")
    suspend fun updateSchedule(
        @Path("storeId") storeId: String,
        @Path("scheduleId") scheduleId: String,
        @Body request: ScheduleUpdate
    ): DataResponse<ScheduleRead>

    @POST("api/stores/{storeId}/schedules/{scheduleId}/shifts")
    suspend fun createShift(
        @Path("storeId") storeId: String,
        @Path("scheduleId") scheduleId: String,
        @Body request: ShiftCreate
    ): DataResponse<ShiftRead>

    @PATCH("api/stores/{storeId}/schedules/{scheduleId}/shifts/{shiftId}")
    suspend fun updateShift(
        @Path("storeId") storeId: String,
        @Path("scheduleId") scheduleId: String,
        @Path("shiftId") shiftId: String,
        @Body request: ShiftUpdate
    ): DataResponse<ShiftRead>

    @DELETE("api/stores/{storeId}/schedules/{scheduleId}/shifts/{shiftId}")
    suspend fun deleteShift(
        @Path("storeId") storeId: String,
        @Path("scheduleId") scheduleId: String,
        @Path("shiftId") shiftId: String
    )

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
        @Query("status") status: String? = null,
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 20
    ): PaginatedResponse<TimeEntryRead>

    @PATCH("api/stores/{storeId}/timesheets/{entryId}")
    suspend fun updateTimesheetEntry(
        @Path("storeId") storeId: String,
        @Path("entryId") entryId: String,
        @Body request: TimeEntryUpdate
    ): DataResponse<TimeEntryRead>

    @GET("api/stores/{storeId}/timesheets/summary")
    suspend fun getTimesheetSummary(
        @Path("storeId") storeId: String,
        @Query("date_from") dateFrom: String,
        @Query("date_to") dateTo: String
    ): DataResponse<TimesheetSummaryResponse>

    // ── Orders ──

    @GET("api/stores/{storeId}/orders")
    suspend fun listOrders(
        @Path("storeId") storeId: String,
        @Query("status") status: String? = null,
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 200
    ): PaginatedResponse<Order>

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

    // ── Manager inventory / iOS InventoryTabView parity ──

    @GET("api/stores/{storeId}/copilot/summary")
    suspend fun getManagerSummary(
        @Path("storeId") storeId: String
    ): DataResponse<ManagerSummary>

    @GET("api/stores/{storeId}/copilot/inventory")
    suspend fun getInventoryInsights(
        @Path("storeId") storeId: String
    ): DataResponse<List<InventoryInsight>>

    @GET("api/stores/{storeId}/copilot/recommendations")
    suspend fun getManagerRecommendations(
        @Path("storeId") storeId: String
    ): DataResponse<List<ManagerRecommendation>>

    @POST("api/stores/{storeId}/copilot/recommendations/analyze")
    suspend fun analyzeInventory(
        @Path("storeId") storeId: String,
        @Body request: Map<String, @JvmSuppressWildcards Any>
    ): DataResponse<Map<String, @JvmSuppressWildcards Any>>

    @POST("api/stores/{storeId}/copilot/recommendations/{recommendationId}/{action}")
    suspend fun updateRecommendation(
        @Path("storeId") storeId: String,
        @Path("recommendationId") recommendationId: String,
        @Path("action") action: String,
        @Body request: RecommendationDecisionBody
    ): DataResponse<ManagerRecommendation>

    // ── Master data / iOS MasterDataView parity ──

    @GET("api/master-data/stats")
    suspend fun getMasterDataStats(): MasterDataStats

    @GET("api/master-data/products")
    suspend fun listMasterDataProducts(
        @Query("launch_only") launchOnly: Boolean = true,
        @Query("needs_price") needsPrice: Boolean = true,
        @Query("purchased_only") purchasedOnly: Boolean = true,
        @Query("supplier") supplier: String? = null
    ): MasterDataProductsResponse

    @PATCH("api/master-data/products/{sku}")
    suspend fun patchMasterDataProduct(
        @Path("sku") sku: String,
        @Body patch: MasterDataProductPatch
    ): MasterDataProductRow

    @POST("api/master-data/export/nec_jewel")
    suspend fun exportNecJewel(
        @Body body: Map<String, @JvmSuppressWildcards Any> = emptyMap()
    ): MasterDataExportResult

    @Multipart
    @POST("api/master-data/ingest/invoice")
    suspend fun ingestInvoice(
        @Part file: MultipartBody.Part
    ): IngestPreview

    @POST("api/master-data/ingest/invoice/commit")
    suspend fun commitInvoice(
        @Body request: IngestCommitRequest
    ): IngestCommitResult

    @POST("api/master-data/ai/recommend_prices")
    suspend fun recommendPrices(
        @Body request: RecommendPricesRequest = RecommendPricesRequest()
    ): PriceRecommendationsResponse
}
